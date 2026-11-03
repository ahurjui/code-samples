import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.enums import OrderStatus, ProviderMode, SignalAction
from app.domain.market import Symbol
from app.domain.risk import RiskParams
from app.domain.signals import Signal
from app.domain.system_state import SystemState
from app.services.config_service import ActiveConfig
from app.services.execution_service import ExecutionService

NOW = datetime(2026, 5, 30, tzinfo=timezone.utc)
SYM = Symbol(base="BTC", quote="USDT", venue_symbol="BTCUSDT")


class FakeExchange:
    def __init__(self, mode):
        self.mode = mode
        self.placed = []

    async def place_order(self, order):
        from dataclasses import replace

        self.placed.append(order)
        return replace(order, status=OrderStatus.FILLED, updated_at=NOW)


def _active(mode=ProviderMode.DRY_RUN, max_order=Decimal("100"), max_open_orders=5):
    from app.domain.enums import Timeframe

    return ActiveConfig(
        version_hash="h" * 64,
        provider="binance",
        mode=mode,
        symbols=("BTC/USDT",),
        timeframe=Timeframe.M1,
        active_strategy={"name": "sma_crossover", "params": {}},
        risk=RiskParams(
            max_position_quote=Decimal("1000"),
            max_order_quote=max_order,
            max_open_orders=max_open_orders,
            max_daily_loss_quote=Decimal("200"),
            max_leverage=Decimal("1"),
            allow_shorting=False,
        ),
        llm={"enabled": False, "provider": "null"},
        activated_at=NOW,
    )


def _signal(action=SignalAction.ENTER_LONG):
    return Signal(
        strategy="sma_crossover",
        symbol=SYM,
        action=action,
        strength=Decimal("1"),
        reason="x",
        candle_open_time=NOW,
    )


def _seed_fresh_guards(session, *, provider="binance", venue_symbol="BTCUSDT"):
    """Seed a fresh candle + account_state_sync audit + symbol_fill_ingest
    recency (issue #468) so the stale-data guard (both the provider-wide and
    the per-symbol branch) passes."""
    from app.repositories.audit import AuditRepository
    from app.repositories.candles import CandleRepository
    from app.repositories.symbol_fill_ingest import SymbolFillIngestRepository

    fresh = datetime.now(timezone.utc)
    CandleRepository(session).upsert(
        provider=provider,
        venue_symbol=venue_symbol,
        base="BTC",
        quote="USDT",
        timeframe="1m",
        open_time=fresh,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
        closed=True,
    )
    AuditRepository(session).add(
        ts=fresh,
        actor="scheduler",
        event_type="account_state_sync",
        detail_json={},
        user_id="alice",
        provider=provider,
    )
    SymbolFillIngestRepository(session).record_success(
        user_id="alice", provider=provider, venue_symbol=venue_symbol, ts=fresh
    )


def test_handle_signal_places_order_and_persists(session):
    _seed_fresh_guards(session)
    session.commit()
    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(), active=_active(), exchange=ex, last_price=Decimal("100")
        )
    )
    session.commit()
    assert placed is not None
    # dry_run does NOT call place_order (no real POST) — spec §5 no-POST contract.
    assert ex.placed == []
    from app.repositories.orders import OrderRepository

    assert len(OrderRepository(session).list(user_id="alice")) == 1


def test_mode_off_ignores_signal_and_audits(session):
    ex = FakeExchange(ProviderMode.OFF)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(),
            active=_active(mode=ProviderMode.OFF),
            exchange=ex,
            last_price=Decimal("100"),
        )
    )
    session.commit()
    assert placed is None
    assert ex.placed == []
    from app.services.audit_service import AuditService

    assert AuditService(session).query(event_type="signal_ignored_mode_off")


def test_risk_rejection_audits_and_does_not_place(session):
    _seed_fresh_guards(session)
    session.commit()
    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(),
            active=_active(max_open_orders=0),  # zero cap -> always rejects
            exchange=ex,
            last_price=Decimal("100"),
        )
    )
    session.commit()
    assert placed is None
    assert ex.placed == []
    from app.services.audit_service import AuditService

    rows = AuditService(session).query(event_type="order_rejected_risk")
    assert rows
    assert rows[0].detail_json.get("guard") == "open_orders"


def test_exit_on_oversized_position_places_full_flat(session):
    """Regression: EXIT must not be blocked by max_order_quote.

    Position of 2 BTC at $100 = notional $200, which exceeds max_order_quote=$50.
    Without reduce_only the risk gate would reject the EXIT order, leaving the
    position stuck. With reduce_only=True the size cap is bypassed and the full
    flat order is placed.
    """
    from app.domain.enums import Side
    from app.domain.trading import Fill
    from app.services.accounting_service import AccountingService

    acc = AccountingService(session, user_id="alice")
    acc.apply_fill(
        provider="binance",
        fill=Fill(
            fill_id="f1",
            client_order_id="c",
            venue_order_id=None,
            symbol=SYM,
            side=Side.BUY,
            price=Decimal("100"),
            quantity=Decimal("2"),
            fee=Decimal("0"),
            fee_currency="USDT",
            ts=NOW,
        ),
    )
    session.commit()

    _seed_fresh_guards(session)
    session.commit()
    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.EXIT),
            active=_active(max_order=Decimal("50")),  # max_order_quote < position notional
            exchange=ex,
            last_price=Decimal("100"),
        )
    )
    session.commit()
    assert placed is not None
    # dry_run routes through _handle_dry_run (no-POST); verify via the persisted row.
    assert ex.placed == []
    from app.repositories.orders import OrderRepository

    orders = OrderRepository(session).list(user_id="alice")
    assert len(orders) == 1
    assert orders[0].quantity == Decimal("2")  # full flat


def test_hold_signal_is_noop(session):
    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.HOLD),
            active=_active(),
            exchange=ex,
            last_price=Decimal("100"),
        )
    )
    assert placed is None
    assert ex.placed == []


def test_alice_order_does_not_touch_bob(session):
    """Effect-asserting: alice's placed order lands only in alice's partition."""
    from app.repositories.orders import OrderRepository

    repo = OrderRepository(session)
    # seed: bob already has one order
    repo.upsert(
        user_id="bob",
        client_order_id="bob-1",
        venue_order_id=None,
        provider="binance",
        mode="dry_run",
        venue_symbol="BTCUSDT",
        base="BTC",
        quote="USDT",
        side="buy",
        type="market",
        quantity=Decimal("1"),
        price=Decimal("100"),
        tif="gtc",
        status="filled",
        config_version_hash="h" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    session.commit()
    before_alice = len(repo.list(user_id="alice"))
    before_bob = len(repo.list(user_id="bob"))

    _seed_fresh_guards(session)
    session.commit()
    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(), active=_active(), exchange=ex, last_price=Decimal("100")
        )
    )
    session.commit()

    assert placed is not None
    assert len(repo.list(user_id="alice")) == before_alice + 1  # delta on alice
    assert len(repo.list(user_id="bob")) == before_bob  # bob untouched


def test_executor_blocks_when_db_state_not_healthy(session):
    """Effect: with DbSystemStateProvider and a persisted non-HEALTHY state, the
    executor places nothing and writes order_blocked_system_state. Orders count
    stays 0."""
    from app.domain.enums import Timeframe
    from app.repositories.orders import OrderRepository
    from app.services.audit_service import AuditService
    from app.services.state_provider import DbSystemStateProvider
    from app.services.system_state_service import SystemStateService

    # Persist TRADING_BLOCKED via a legal path: STARTING -> SYNCING -> TRADING_BLOCKED
    svc = SystemStateService(session)
    svc.current()  # STARTING
    asyncio.run(svc.transition_to(SystemState.SYNCING, reason="sync", actor="t"))
    asyncio.run(svc.transition_to(SystemState.TRADING_BLOCKED, reason="ws", actor="t"))

    active = ActiveConfig(
        version_hash="h" * 64,
        provider="binance",
        mode=ProviderMode.DRY_RUN,
        symbols=("BTC/USDT",),
        timeframe=Timeframe.M1,
        active_strategy={"name": "sma_crossover", "params": {}},
        risk=RiskParams(
            max_position_quote=Decimal("1000"),
            max_order_quote=Decimal("100"),
            max_open_orders=5,
            max_daily_loss_quote=Decimal("200"),
            max_leverage=Decimal("1"),
            allow_shorting=False,
        ),
        llm={"enabled": False, "provider": "null"},
        activated_at=None,
    )
    sig = Signal(
        strategy="sma_crossover",
        symbol=SYM,
        action=SignalAction.ENTER_LONG,
        strength=Decimal("1"),
        reason="x",
        candle_open_time=NOW,
    )

    class _Ex:
        mode = ProviderMode.DRY_RUN

        async def test_order(self, order):
            return order

    _seed_fresh_guards(session)
    session.commit()
    before = len(OrderRepository(session).list(user_id="alice"))
    result = asyncio.run(
        ExecutionService(
            session, user_id="alice", state_provider=DbSystemStateProvider(session)
        ).handle_signal(signal=sig, active=active, exchange=_Ex(), last_price=Decimal("100"))
    )
    assert result is None
    assert len(OrderRepository(session).list(user_id="alice")) == before  # nothing placed
    blocked = AuditService(session).query(event_type="order_blocked_system_state")
    assert len(blocked) == 1
    assert blocked[0].detail_json["state"] == "trading_blocked"


@pytest.mark.parametrize("mode", [ProviderMode.DRY_RUN, ProviderMode.TESTNET, ProviderMode.LIVE])
def test_guard_rejection_is_mode_invariant(session, mode):
    """Same blocking state (stale candle) → same order_rejected_risk(guard=
    stale_data) in dry_run, testnet, and live. Mode parity (spec §8)."""
    from datetime import timedelta

    from app.repositories.candles import CandleRepository
    from app.services.audit_service import AuditService

    # candle_age must exceed the timeframe-scaled max_candle (60 + 1920 = 1980s
    # for 1m) so this stays on the candle-stale branch (kind="candle"), not the
    # missing-sync branch.
    CandleRepository(session).upsert(
        provider="binance",
        venue_symbol="BTCUSDT",
        base="BTC",
        quote="USDT",
        timeframe="1m",
        open_time=NOW - timedelta(seconds=3000),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
        closed=True,
    )
    session.commit()

    ex = FakeExchange(mode)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(), active=_active(mode=mode), exchange=ex, last_price=Decimal("100")
        )
    )
    session.commit()
    assert placed is None
    assert ex.placed == []
    rows = AuditService(session).query(event_type="order_rejected_risk", user_id="alice")
    assert rows
    assert rows[0].detail_json.get("guard") == "stale_data"
    assert rows[0].detail_json.get("guard_detail", {}).get("kind") == "candle"


def test_executor_uses_core_risk_guards_with_guard_field(session):
    """A duplicate-position breach surfaces via CoreRiskGuards through the
    executor as order_rejected_risk carrying guard='duplicate_position'."""
    from app.repositories.positions import PositionRepository
    from app.services.audit_service import AuditService

    # Stale-data prerequisites: fresh candle + fresh account_state_sync audit
    # row + fresh symbol_fill_ingest recency (issue #468).
    _seed_fresh_guards(session)
    # Existing open position → ENTER must be rejected as duplicate_position.
    PositionRepository(session).upsert(
        user_id="alice",
        provider="binance",
        venue_symbol="BTCUSDT",
        base="BTC",
        quote="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        updated_at=NOW,
    )
    session.commit()

    ex = FakeExchange(ProviderMode.DRY_RUN)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(), active=_active(), exchange=ex, last_price=Decimal("100")
        )
    )
    session.commit()
    assert placed is None
    rows = AuditService(session).query(event_type="order_rejected_risk", user_id="alice")
    assert rows
    assert rows[0].detail_json.get("guard") == "duplicate_position"


def test_unknown_terminal_blocks_replacement(session):
    """§5.5-executor: an order in unknown_terminal status must be in _LIVE_STATUSES
    so a strategy replay producing the same client_order_id skips placement."""
    from app.domain.enums import OrderStatus
    from app.services.execution_service import _LIVE_STATUSES

    assert OrderStatus.UNKNOWN_TERMINAL.value in _LIVE_STATUSES


# ---------------------------------------------------------------------------
# #134 D5: provider-aware executor gate, end-to-end through handle_signal
# ---------------------------------------------------------------------------


def _seed_module_state(session, state: str) -> None:
    from app.domain.system_state import SystemState
    from app.services.system_state_service import SystemStateService

    svc = SystemStateService(session)
    svc.current()  # lazy STARTING
    path = {
        "healthy": [SystemState.SYNCING, SystemState.HEALTHY],
        "degraded": [SystemState.SYNCING, SystemState.HEALTHY, SystemState.DEGRADED],
        "trading_blocked": [
            SystemState.SYNCING,
            SystemState.HEALTHY,
            SystemState.TRADING_BLOCKED,
        ],
    }[state]
    for s in path:
        asyncio.run(svc.transition_to(s, reason="t", actor="t"))


def _pair_provider(session, *, mode):
    from app.services.state_provider import DbProviderAwareStateProvider

    return DbProviderAwareStateProvider(session, user_id="alice", provider="binance", mode=mode)


def _order_count(session, user_id="alice"):
    from app.repositories.orders import OrderRepository

    return len(OrderRepository(session).list(user_id=user_id))


def _blocked_audits(session):
    from app.db.orm import AuditLogRow

    return session.query(AuditLogRow).filter_by(event_type="order_blocked_system_state").all()


def test_dirty_pair_blocked_and_clean_sibling_mode_proceeds(session):
    """#134 §7 (a)+(b)+(h): the DEGRADED (alice, binance, testnet) pair is
    blocked with an effective-state audit, while the SAME user's clean dry_run
    sibling pair proceeds in the same scenario (mode isolation)."""
    from app.domain.provider_state import ProviderState
    from app.services.provider_state_service import ProviderStateService

    _seed_fresh_guards(session)
    _seed_module_state(session, "healthy")
    ProviderStateService(session).transition_to(
        "alice", "binance", "testnet", ProviderState.DEGRADED, reason="drift", actor="t"
    )
    session.commit()

    # (a) dirty testnet pair → blocked, audited with the EFFECTIVE state
    blocked = asyncio.run(
        ExecutionService(
            session,
            user_id="alice",
            state_provider=_pair_provider(session, mode="testnet"),
        ).handle_signal(
            signal=_signal(),
            active=_active(mode=ProviderMode.TESTNET),
            exchange=FakeExchange(ProviderMode.TESTNET),
            last_price=Decimal("100"),
        )
    )
    assert blocked is None
    assert _order_count(session) == 0
    audits = _blocked_audits(session)
    assert audits and audits[-1].detail_json["state"] == "degraded"

    # (b)+(h) clean dry_run sibling of the SAME (user, provider) proceeds
    sig2 = Signal(
        strategy="sma_crossover",
        symbol=SYM,
        action=SignalAction.ENTER_LONG,
        strength=Decimal("1"),
        reason="x",
        candle_open_time=NOW + timedelta(minutes=1),
    )
    placed = asyncio.run(
        ExecutionService(
            session,
            user_id="alice",
            state_provider=_pair_provider(session, mode="dry_run"),
        ).handle_signal(
            signal=sig2,
            active=_active(),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    assert placed is not None
    assert _order_count(session) == 1


def test_module_degraded_pair_healthy_proceeds_with_audited_lazy_init(session):
    """#134 §7 (c) + D5 headline: module DEGRADED + missing pair row ⇒
    deterministic lazy-HEALTHY init (audited) ⇒ the order proceeds."""
    from app.db.orm import AuditLogRow, ProviderStateRow

    _seed_fresh_guards(session)
    _seed_module_state(session, "degraded")
    session.commit()

    placed = asyncio.run(
        ExecutionService(
            session,
            user_id="alice",
            state_provider=_pair_provider(session, mode="dry_run"),
        ).handle_signal(
            signal=_signal(),
            active=_active(),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    assert placed is not None
    assert _order_count(session) == 1
    [row] = session.query(ProviderStateRow).all()
    assert (row.user_id, row.provider, row.mode, row.state) == (
        "alice",
        "binance",
        "dry_run",
        "healthy",
    )
    assert session.query(AuditLogRow).filter_by(event_type="provider_state_lazy_init").count() == 1


def test_module_trading_blocked_blocks_regardless_of_pair(session):
    """#134 §7 (e): globally-blocking module state wins before any pair lookup."""
    from app.services.provider_state_service import ProviderStateService

    _seed_fresh_guards(session)
    _seed_module_state(session, "trading_blocked")
    ProviderStateService(session).current_or_initialize("alice", "binance", "dry_run")
    session.commit()

    blocked = asyncio.run(
        ExecutionService(
            session,
            user_id="alice",
            state_provider=_pair_provider(session, mode="dry_run"),
        ).handle_signal(
            signal=_signal(),
            active=_active(),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    assert blocked is None
    assert _order_count(session) == 0
    audits = _blocked_audits(session)
    assert audits and audits[-1].detail_json["state"] == "trading_blocked"


def test_pair_kill_switched_blocks_decisively(session):
    """#134 §7 (g): pair KILL_SWITCHED blocks the pair; terminal, no recovery."""
    from app.domain.provider_state import ProviderState
    from app.services.provider_state_service import ProviderStateService

    _seed_fresh_guards(session)
    _seed_module_state(session, "healthy")
    ProviderStateService(session).transition_to(
        "alice", "binance", "dry_run", ProviderState.KILL_SWITCHED, reason="kill", actor="t"
    )
    session.commit()

    blocked = asyncio.run(
        ExecutionService(
            session,
            user_id="alice",
            state_provider=_pair_provider(session, mode="dry_run"),
        ).handle_signal(
            signal=_signal(),
            active=_active(),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    assert blocked is None
    assert _order_count(session) == 0
    audits = _blocked_audits(session)
    assert audits and audits[-1].detail_json["state"] == "kill_switched"


def test_state_lookup_failure_fails_closed_no_order(session, monkeypatch):
    """#134 §7 (d): a raising state lookup propagates out of handle_signal —
    the order is NOT placed. No silent fail-open."""
    import pytest

    _seed_fresh_guards(session)
    _seed_module_state(session, "healthy")
    session.commit()

    def _boom(self):
        raise RuntimeError("state backend down")

    monkeypatch.setattr("app.services.system_state_service.SystemStateService.current", _boom)
    with pytest.raises(RuntimeError):
        asyncio.run(
            ExecutionService(
                session,
                user_id="alice",
                state_provider=_pair_provider(session, mode="dry_run"),
            ).handle_signal(
                signal=_signal(),
                active=_active(),
                exchange=FakeExchange(ProviderMode.DRY_RUN),
                last_price=Decimal("100"),
            )
        )
    assert _order_count(session) == 0


# ---------------------------------------------------------------------------
# Change A on the live-trade seam (spec §5.3): typed error in order_place_error audit
# ---------------------------------------------------------------------------


def test_live_place_order_no_credentials_audits_typed_error(session):
    """TESTNET _handle_live → place_order with credentials=None hits the signing seam.

    Change A makes the seam raise BinanceCredentialsMissing; _handle_live's
    `except Exception` writes order_place_error with error=str(exc). Assert the
    audited error is the typed credentials message, NOT a raw AttributeError.
    """
    from app.exchanges.binance.adapter import BinanceExchange
    from app.services.audit_service import AuditService

    _seed_fresh_guards(session)
    session.commit()

    # Real adapter, TESTNET, NO credentials → signed place_order reaches the guarded seam.
    exchange = BinanceExchange(mode=ProviderMode.TESTNET, credentials=None)
    svc = ExecutionService(session, user_id="alice")
    placed = asyncio.run(
        svc.handle_signal(
            signal=_signal(),
            active=_active(mode=ProviderMode.TESTNET),
            exchange=exchange,
            last_price=Decimal("100"),
        )
    )
    session.commit()

    assert placed is None  # _handle_live returns None on place_order failure
    rows = AuditService(session).query(event_type="order_place_error")
    assert rows, "expected an order_place_error audit row"
    err = rows[0].detail_json.get("error", "")
    # Typed message present; opaque AttributeError absent.
    assert "credentials not configured" in err
    assert "NoneType" not in err
    assert "has no attribute" not in err


# ---------------------------------------------------------------------------
# Step 4.1: live synthetic fill keeps fee=0 (INV3a / AC5)
# ---------------------------------------------------------------------------


def test_live_synthetic_fill_fee_is_zero(session):
    """TESTNET/LIVE _handle_live no longer applies fills at order time (INV3) —
    account_state_sync is the sole accounting writer for real fills. A
    synchronously-FILLED order must persist zero FillRows and leave the
    position unchanged until the sync ingests the venue trade."""
    from app.db.orm import FillRow
    from app.repositories.positions import PositionRepository

    _seed_fresh_guards(session)
    session.commit()

    svc = ExecutionService(session, user_id="alice")
    asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.ENTER_LONG),
            active=_active(mode=ProviderMode.TESTNET),
            exchange=FakeExchange(ProviderMode.TESTNET),
            last_price=Decimal("100"),
        )
    )
    session.commit()

    assert session.query(FillRow).all() == []
    assert PositionRepository(session).get("alice", "binance", "BTCUSDT") is None


# ---------------------------------------------------------------------------
# Step 5.1: dry-run fill-fee = cost.total (AC1 / INV1)
# ---------------------------------------------------------------------------


def test_dry_run_fill_fee_equals_cost_total(session):
    """Dry-run BUY 1@100 with default bps (taker=10, slippage=5, spread=2 = 17 bps):
    cost.total = 100 × 17/10000 = 0.17. FillRow.fee must equal Decimal('0.17') (AC1)."""
    from app.db.orm import FillRow

    _seed_fresh_guards(session)
    session.commit()

    svc = ExecutionService(session, user_id="alice")
    asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.ENTER_LONG),
            active=_active(mode=ProviderMode.DRY_RUN, max_order=Decimal("100")),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    session.commit()

    fill_rows = session.query(FillRow).all()
    assert len(fill_rows) == 1
    fill = fill_rows[0]
    assert fill.fee_currency == "USDT"
    assert fill.fill_id.startswith("dry_run_")
    # 100 × 17 bps / 10000 = 0.17 (Decimal-exact per INV1)
    assert fill.fee.quantize(Decimal("0.01")) == Decimal("0.17")


# ---------------------------------------------------------------------------
# AC6: config off-switch — zero bps reproduces gross P&L
# ---------------------------------------------------------------------------


def test_dry_run_zero_bps_yields_gross_pnl(session):
    """Setting all cost-model bps to 0 makes cost.total = 0 so FillRow.fee = 0
    and round-trip realized_pnl equals the raw gross delta (AC6 soft off-switch)."""
    from app.db.orm import FillRow, PositionRow
    from app.settings import Settings

    zero_bps = Settings(
        cost_model_maker_fee_bps=0,
        cost_model_taker_fee_bps=0,
        cost_model_slippage_bps=0,
        cost_model_spread_bps=0,
        dry_run_validate_with_test_order=False,
    )
    _seed_fresh_guards(session)
    session.commit()

    svc = ExecutionService(session, user_id="alice", settings=zero_bps)

    # Entry: BUY 1@100 (max_order_quote=100, last_price=100 → qty=1)
    asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.ENTER_LONG),
            active=_active(mode=ProviderMode.DRY_RUN, max_order=Decimal("100")),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    session.commit()

    fill_rows = session.query(FillRow).all()
    assert len(fill_rows) == 1
    assert fill_rows[0].fee == Decimal("0")  # zero bps → cost.total = 0

    pos = session.query(PositionRow).one()
    assert pos.realized_pnl == Decimal("0")  # entry: no close yet

    # Seed fresh guards again for the exit signal
    _seed_fresh_guards(session)
    session.commit()

    # Close: EXIT signal — use a distinct candle_open_time so the deterministic
    # client_order_id differs from the entry order (avoids pre-flight dedup).
    exit_signal = Signal(
        strategy="sma_crossover",
        symbol=SYM,
        action=SignalAction.EXIT,
        strength=Decimal("1"),
        reason="x",
        candle_open_time=NOW + timedelta(minutes=1),
    )
    asyncio.run(
        svc.handle_signal(
            signal=exit_signal,
            active=_active(mode=ProviderMode.DRY_RUN, max_order=Decimal("200")),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("110"),
        )
    )
    session.commit()

    pos = (
        session.query(PositionRow)
        .filter_by(user_id="alice", provider="binance", venue_symbol="BTCUSDT")
        .one()
    )
    # realized_pnl == 10 (gross: 110-100=10), NOT less — zero bps reproduces prior behavior
    assert pos.realized_pnl == Decimal("10")


# ---------------------------------------------------------------------------
# Parent AC2: FILLED-has-one-fill invariant on the synthetic dry-run path
# ---------------------------------------------------------------------------


def test_filled_has_one_fill_invariant(session):
    """Every synthetic dry-run order that completes produces exactly one FillRow
    (closes parent #282 AC2). Seed → execute → re-query → assert count == 1."""
    from app.db.orm import FillRow, OrderRow

    _seed_fresh_guards(session)
    session.commit()

    svc = ExecutionService(session, user_id="alice")
    asyncio.run(
        svc.handle_signal(
            signal=_signal(SignalAction.ENTER_LONG),
            active=_active(mode=ProviderMode.DRY_RUN, max_order=Decimal("100")),
            exchange=FakeExchange(ProviderMode.DRY_RUN),
            last_price=Decimal("100"),
        )
    )
    session.commit()

    order = session.query(OrderRow).filter_by(user_id="alice").one()
    assert order.status == OrderStatus.FILLED.value

    fill_count = (
        session.query(FillRow)
        .filter_by(user_id="alice", client_order_id=order.client_order_id)
        .count()
    )
    assert fill_count == 1, (
        f"Expected exactly 1 FillRow for FILLED order {order.client_order_id!r}, got {fill_count}"
    )
