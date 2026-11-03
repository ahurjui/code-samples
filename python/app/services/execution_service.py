from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.cost_model import CostEstimate, CostModel
from app.domain.enums import (
    OrderStatus,
    OrderType,
    ProviderMode,
    Side,
    SignalAction,
    TimeInForce,
)
from app.domain.errors import RiskGuardError, RiskRejection, RiskViolationError
from app.domain.money import quantize_to_step
from app.domain.signals import Signal
from app.domain.sizing import TINY_STOP_FLOOR, compute_atr_position_size
from app.domain.system_state import SystemStateProvider
from app.domain.trading import Fill, Order
from app.notifications.base import Notifier
from app.notifications.null import NullNotifier
from app.repositories.fills import FillRepository
from app.repositories.orders import OrderRepository
from app.services.accounting_service import AccountingService
from app.services.audit_service import AuditService
from app.services.idempotency import deterministic_client_order_id
from app.services.core_risk_guards import CoreRiskGuards
from app.services.extended_risk_layer import ExtendedRiskLayer
from app.services.sizing_service import source_atr14, source_kelly_fraction, MIN_KELLY_TRADES
from app.services.state_provider import AlwaysHealthyStateProvider
from app.settings import Settings

_ENTRY_SIDE = {SignalAction.ENTER_LONG: Side.BUY, SignalAction.ENTER_SHORT: Side.SELL}


def _signum(x: Decimal) -> int:
    """-1/0/+1 sign of x, for the EXIT overlay sign-flip clamp comparison (#466 INV3)."""
    return (x > Decimal("0")) - (x < Decimal("0"))


# Local statuses that mean "this id already produced a live order" — a replay must
# skip rather than re-place. REJECTED is a terminal failure and may be retried, so
# it is intentionally excluded.
_LIVE_STATUSES = {
    OrderStatus.PENDING.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.FILLED.value,
    OrderStatus.CANCELED.value,
    OrderStatus.EXPIRED.value,
    OrderStatus.UNKNOWN_TERMINAL.value,
}

# Alias for readability; the value lives in domain/sizing to be shared with the
# admin sizing router (INV5 parity).
_TINY_FLOOR = TINY_STOP_FLOOR


class ExecutionService:
    def __init__(
        self,
        session: Session,
        *,
        user_id: str,
        state_provider: SystemStateProvider | None = None,
        notifier: Notifier | None = None,
        settings: Settings | None = None,
        macro_provider=None,
    ) -> None:
        self._user_id = user_id
        self._session = session
        self._orders = OrderRepository(session)
        self._fills = FillRepository(session)
        self._accounting = AccountingService(session, user_id=user_id)
        self._audit = AuditService(session)
        self._state_provider = state_provider or AlwaysHealthyStateProvider()
        self._notifier = notifier or NullNotifier()
        self._settings = settings or Settings()
        if macro_provider is None:
            from app.domain.macro_risk import build_macro_risk_provider

            self._macro_provider = build_macro_risk_provider(
                self._settings, bind=session.get_bind()
            )
        else:
            self._macro_provider = macro_provider
        self._cost_model = CostModel(
            maker_fee_bps=Decimal(self._settings.cost_model_maker_fee_bps),
            taker_fee_bps=Decimal(self._settings.cost_model_taker_fee_bps),
            slippage_bps=Decimal(self._settings.cost_model_slippage_bps),
            spread_bps=Decimal(self._settings.cost_model_spread_bps),
        )

    def _audit_worker(
        self, *, event_type: str, detail: dict, active, subject_id: str | None = None
    ) -> None:
        """Record a worker-actor audit row, defaulting the constant fields
        (actor / provider / config_version_hash / user_id) shared by every
        executor event."""
        self._audit.record(
            actor="worker",
            event_type=event_type,
            detail=detail,
            provider=active.provider,
            config_version_hash=active.version_hash,
            subject_id=subject_id,
            user_id=self._user_id,
        )

    def _audit_worker_once(self, *, event_type: str, subject_id: str, detail: dict, active) -> None:
        """`_audit_worker`, skipped if an identical (event_type, subject_id)
        row already exists — same-candle replays must not duplicate a single
        decision in the audit stream."""
        if not self._audit.exists(
            event_type=event_type, subject_id=subject_id, user_id=self._user_id
        ):
            self._audit_worker(
                event_type=event_type, detail=detail, active=active, subject_id=subject_id
            )

    async def _safe_notify(self, *, event: str, detail: dict, active) -> None:
        """Notify, but never let a notifier failure abort/roll back a trade."""
        try:
            await self._notifier.notify(event=event, detail=detail)
        except Exception as exc:  # noqa: BLE001 — notifier is best-effort
            # Never record str(exc): httpx.HTTPStatusError embeds the full
            # request URL (including the bot token) in its string representation.
            # Record only the exception type and HTTP status code (if present).
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error_repr = (
                f"{type(exc).__name__}:{status}" if status is not None else type(exc).__name__
            )
            self._audit_worker(
                event_type="notify_failed",
                detail={"event": event, "error": error_repr},
                active=active,
            )

    def _entry_quantity(self, *, signal: Signal, active, last_price: Decimal) -> Decimal:
        """Compute pre-quantize entry quantity.

        If ``active.risk.sizing_mode`` is ``None`` or ``"fixed"``, returns the
        byte-identical fixed-fraction result:
            budget = max_order_quote * signal.strength
            raw_qty = budget / last_price  (or 0 if last_price <= 0)

        For ``"atr_adjusted"``, attempts to read ATR-14, derive a stop distance,
        compute ATR-based notional, clamp to ``max_order_quote``, and convert to
        quantity.  Any failure in this path — including non-finite ATR, insufficient
        candles, corrupt feature data, or zero stop distance — silently degrades to
        fixed-fraction and audits a ``sizing_fallback_fixed`` event (INV4).

        For ``"kelly_capped"``, performs the same ATR sizing first, then additionally
        clamps the notional to ``kelly_fraction × Kelly_estimate × capital_base_quote``
        (INV2 — monotone: the Kelly cap can only reduce, never enlarge, the ATR
        notional).  Degrades to ATR-only sizing when no edge estimate is available or
        when ``kelly_fraction`` is not configured (legacy config guard — INV5), auditing
        a ``sizing_kelly_skipped`` event with the skip reason.

        Returns:
            Decimal: the raw (unquantized) entry quantity.
        """
        risk = active.risk
        # ---- Fixed-fraction modes ----
        if risk.sizing_mode in (None, "fixed"):
            budget = risk.max_order_quote * signal.strength
            return (budget / last_price) if last_price > 0 else Decimal("0")

        # ---- ATR-adjusted modes (atr_adjusted: ATR only; kelly_capped: ATR followed by fractional-Kelly clamp) ----
        def _fallback(reason: str) -> Decimal:
            self._audit_worker(
                event_type="sizing_fallback_fixed",
                detail={"reason": reason},
                active=active,
            )
            budget = risk.max_order_quote * signal.strength
            return (budget / last_price) if last_price > 0 else Decimal("0")

        try:
            # -- Source ATR-14 --
            atr, early_reason = source_atr14(
                self._session,
                provider=active.provider,
                symbol=signal.symbol,
                timeframe=active.timeframe,
            )
            if early_reason is not None:
                return _fallback(early_reason)

            # atr is not None here (source_atr14 guarantees this when early_reason is None)
            # Validate: must be finite and >= 0 (zero is valid — flat regime flows to
            # stop-distance tiny-floor guard downstream).
            if atr is None:
                return _fallback("no_atr")
            if not atr.is_finite():
                return _fallback("non_finite_atr")

            # -- Derive stop distance --
            # Prefer signal.stop_price when it is on the correct side of last_price.
            stop_distance: Decimal | None = None
            if signal.stop_price is not None:
                if signal.action is SignalAction.ENTER_LONG:
                    raw_dist = last_price - signal.stop_price
                else:
                    # SHORT: stop_price should be above last_price
                    raw_dist = signal.stop_price - last_price
                if raw_dist > _TINY_FLOOR:
                    stop_distance = raw_dist
                # If wrong side or too small, fall through to ATR-multiplier branch

            if stop_distance is None:
                # ATR-multiplier branch
                atr_multiplier = risk.atr_multiplier
                stop_distance = atr_multiplier * atr

            # -- Final tiny-floor guard (catches zero ATR × multiplier) --
            if stop_distance <= _TINY_FLOOR:
                return _fallback("zero_stop_distance")

            # -- Guard last_price before division --
            if last_price <= Decimal("0"):
                return _fallback("zero_last_price")

            # -- Compute ATR-based quantity --
            capital = risk.capital_base_quote
            risk_pct = risk.risk_pct_per_trade

            # compute_atr_position_size returns quantity (base units); convert to notional
            atr_qty = compute_atr_position_size(
                capital=capital,
                risk_pct_per_trade=risk_pct,
                stop_distance_quote=stop_distance,
            )
            atr_notional = atr_qty * last_price

            # -- Clamp to max_order_quote (INV6: downstream max_position_quote guard unchanged) --
            clamped_notional = min(atr_notional, risk.max_order_quote)

            # -- Kelly cap (kelly_capped mode only) --
            final_notional = clamped_notional  # default: ATR notional used if Kelly skips
            if risk.sizing_mode == "kelly_capped":
                kelly_fraction_config = risk.kelly_fraction
                if kelly_fraction_config is None:
                    # INV5: legacy config without kelly_fraction; skip cap, emit not_configured
                    self._audit_worker(
                        event_type="sizing_kelly_skipped",
                        detail={"reason": "not_configured"},
                        active=active,
                    )
                else:
                    estimate, reason = source_kelly_fraction(
                        self._session, user_id=self._user_id, min_trades=MIN_KELLY_TRADES
                    )
                    if estimate is None:
                        self._audit_worker(
                            event_type="sizing_kelly_skipped",
                            detail={"reason": reason},
                            active=active,
                        )
                    else:
                        kelly_notional = kelly_fraction_config * estimate * risk.capital_base_quote
                        final_notional = min(clamped_notional, kelly_notional)  # INV2: monotone
                        self._audit_worker(
                            event_type="sizing_kelly_applied",
                            detail={
                                "kelly_estimate": str(estimate),
                                "kelly_fraction": str(kelly_fraction_config),
                                "kelly_notional": str(kelly_notional),
                                "final_notional": str(final_notional),
                            },
                            active=active,
                        )

            # -- Convert to quantity --
            raw_qty = final_notional / last_price

            # -- Audit success --
            self._audit_worker(
                event_type="sizing_atr_applied",
                detail={
                    "atr_14": str(atr),
                    "stop_distance": str(stop_distance),
                    "notional": str(clamped_notional),
                },
                active=active,
            )
            return raw_qty

        except Exception:  # noqa: BLE001 — INV4: no exception may escape sizing path
            try:
                return _fallback("no_atr")
            except Exception:  # noqa: BLE001 — INV1: prevent _fallback flush errors from escaping
                budget = risk.max_order_quote * signal.strength
                return (
                    quantize_to_step(budget / last_price, Decimal("0.00000001"))
                    if last_price > 0
                    else Decimal("0")
                )

    async def handle_signal(self, *, signal: Signal, active, exchange, last_price: Decimal):
        if signal.action is SignalAction.HOLD:
            return None

        if active.mode is ProviderMode.OFF:
            self._audit_worker(
                event_type="signal_ignored_mode_off",
                detail={"symbol": str(signal.symbol), "action": signal.action.value},
                active=active,
            )
            return None

        symbol = signal.symbol
        position = self._accounting.position(
            provider=active.provider, venue_symbol=symbol.venue_symbol
        )

        if signal.action is not SignalAction.EXIT:
            side = _ENTRY_SIDE.get(signal.action, Side.BUY)  # pragma: no mutate
            raw_qty = self._entry_quantity(signal=signal, active=active, last_price=last_price)
            qty = quantize_to_step(raw_qty, Decimal("0.00000001"))

        client_order_id = deterministic_client_order_id(
            strategy_id=signal.strategy,
            venue_symbol=symbol.venue_symbol,
            signal_timestamp=signal.candle_open_time,
        )

        # Pre-flight dedup: an existing non-terminal-failure order for this id is a
        # replay — skip + audit.
        existing = self._orders.get(self._user_id, client_order_id)
        if existing is not None and existing.status in _LIVE_STATUSES:
            # #427: dedup on (user_id, event_type, subject_id) — this replay guard
            # re-fires every tick for the same in-flight order, so without the
            # existence check the audit stream duplicates a single decision.
            if not self._audit.exists(
                event_type="signal_replay_skipped",
                subject_id=client_order_id,
                user_id=self._user_id,
            ):
                self._audit_worker(
                    event_type="signal_replay_skipped",
                    detail={"client_order_id": client_order_id, "status": existing.status},
                    active=active,
                    subject_id=client_order_id,
                )
            return None

        now = datetime.now(timezone.utc)
        order_type = (
            OrderType.LIMIT if self._settings.default_order_type == "limit" else OrderType.MARKET
        )

        if signal.action is SignalAction.EXIT:
            # #466: size/gate the flatten from an order-reconciled net rather than
            # the local positions row alone — during the bounded pre-sync window
            # the row can be stale (hazard 2: a legitimate flatten silently
            # dropped) or stale-nonzero after a venue-filled exit (hazard 5: a
            # duplicate flatten placed). This block runs AFTER the replay dedup
            # above (INV5) so a same-candle replay never reaches it, and AFTER
            # client_order_id so both new audits carry it as subject_id.
            net_row = position.quantity if position is not None else Decimal("0")
            overlay = self._fills.unsynced_filled_order_net(
                user_id=self._user_id,
                provider=active.provider,
                venue_symbol=symbol.venue_symbol,
                mode=active.mode.value,
                since=now - timedelta(seconds=self._settings.risk_max_account_sync_age_s),
            )
            net_effective = net_row + overlay
            # Captured pre-clamp so the rescue-audit predicate below can still see
            # the disagreement the clamp resolves (INV3) — evaluating it against
            # the post-clamp net_effective would silently suppress the audit on
            # the single most safety-critical numerical intervention.
            net_effective_raw = net_effective
            if net_row != 0 and _signum(net_effective) == -_signum(net_row):
                # Fail-safe clamp: the overlay alone would flip the row's sign —
                # untrusted. Close only the row-implied exposure; never cross zero.
                net_effective = net_row

            if net_effective == 0:
                self._audit_worker_once(
                    event_type="exit_flatten_gated",
                    subject_id=client_order_id,
                    detail={"net_row": str(net_row), "overlay": str(overlay)},
                    active=active,
                )
                return None

            side = Side.SELL if net_effective > 0 else Side.BUY  # pragma: no mutate
            raw_qty = abs(net_effective)
            qty = quantize_to_step(raw_qty, Decimal("0.00000001"))

            if net_row == 0 or net_effective_raw != net_row:
                self._audit_worker_once(
                    event_type="exit_size_from_overlay",
                    subject_id=client_order_id,
                    detail={
                        "net_row": str(net_row),
                        "overlay": str(overlay),
                        "net_effective": str(net_effective),
                        "net_effective_raw": str(net_effective_raw),
                    },
                    active=active,
                )

        order = Order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=qty,
            price=last_price,
            tif=TimeInForce.GTC,
            status=OrderStatus.PENDING,  # overridden before persistence by both handlers
            venue_order_id=None,
            mode=active.mode,
            created_at=now,
            updated_at=now,  # overridden before persistence by both handlers
            reduce_only=signal.action is SignalAction.EXIT,
        )

        # Risk gate.
        guards = CoreRiskGuards(
            self._session,
            user_id=self._user_id,
            provider=active.provider,
            risk=active.risk,
            settings=self._settings,
        )
        advisories: list[str] = []  # pragma: no mutate
        try:
            guards.validate(
                order=order,
                reduce_only=signal.action is SignalAction.EXIT,
                timeframe=active.timeframe.value,
            )
            extended = ExtendedRiskLayer(
                self._session,
                user_id=self._user_id,
                provider=active.provider,
                mode=active.mode,
                params=active.risk,
                settings=self._settings,
                macro_provider=self._macro_provider,
            )
            # pragma: no mutate start
            advisories = extended.validate(
                order=order, reduce_only=signal.action is SignalAction.EXIT
            )
            # pragma: no mutate end
        except RiskRejection as exc:
            detail: dict = {"reason": str(exc), "symbol": str(symbol), "quantity": str(qty)}
            if isinstance(exc, RiskGuardError):
                detail["guard"] = exc.guard
                detail["guard_detail"] = exc.detail
            elif isinstance(exc, RiskViolationError):
                detail["violation"] = exc.violation
                detail["severity"] = exc.severity
            self._audit_worker(
                event_type="order_rejected_risk",
                detail=detail,
                active=active,
                subject_id=client_order_id,
            )
            await self._safe_notify(
                event="rejection",
                detail={"reason": str(exc), "symbol": str(symbol)},
                active=active,
            )
            return None

        # Audit-before-place: flush a trace BEFORE any exchange call, now that the
        # risk gate has passed. On a caught exchange error the row is still
        # committed when the session closes; the deterministic clientOrderId
        # guards against venue-level duplicates on retry.
        self._audit_worker(
            event_type="order_pending",
            detail={"client_order_id": client_order_id, "quantity": str(qty)},
            active=active,
            subject_id=client_order_id,
        )

        for advisory in advisories:
            self._audit_worker(
                event_type=advisory,
                detail={"provider": active.provider},
                active=active,
                subject_id=client_order_id,
            )
            # pragma: no mutate start
            await self._safe_notify(
                event=advisory,
                detail={"provider": active.provider},
                active=active,
            )
            # pragma: no mutate end

        # System-state gate.
        state = self._state_provider.current()
        if not state.permits_trading:
            self._audit_worker(
                event_type="order_blocked_system_state",
                detail={"state": state.value, "client_order_id": client_order_id},
                active=active,
                subject_id=client_order_id,
            )
            return None

        # dry_run: no POST.
        if active.mode is ProviderMode.DRY_RUN:
            return await self._handle_dry_run(
                order=order, active=active, exchange=exchange, symbol=symbol, qty=qty
            )

        # testnet / live: identical path; only the injected exchange differs.
        return await self._handle_live(
            order=order, active=active, exchange=exchange, symbol=symbol, qty=qty
        )

    async def _handle_dry_run(self, *, order, active, exchange, symbol, qty):
        # pragma: no mutate start
        cost = self._cost_model.estimate(
            price=order.price if order.price is not None else Decimal("0"),
            quantity=qty,
            order_type=order.type,
        )
        # pragma: no mutate end
        test_result = "skipped"
        if self._settings.dry_run_validate_with_test_order:
            try:
                await exchange.test_order(order)
                test_result = "skipped_dry_run"
            except Exception as exc:  # noqa: BLE001
                test_result = f"error: {exc}"
        self._audit_worker(
            event_type="order_dry_run",
            detail={
                "client_order_id": order.client_order_id,
                "mode": active.mode.value,
                "would_place": True,
                "cost": cost.as_dict(),
                "test_order_result": test_result,
                "quantity": str(qty),
            },
            active=active,
            subject_id=order.client_order_id,
        )
        placed = replace(
            order, status=OrderStatus.FILLED, updated_at=datetime.now(timezone.utc)
        )  # pragma: no mutate
        self._persist_order(placed=placed, active=active, symbol=symbol)
        self._record_fill(
            placed=placed, active=active, symbol=symbol, fill_id_prefix="dry_run_", cost=cost
        )
        # pragma: no mutate start
        await self._safe_notify(
            event="fill",
            detail={"client_order_id": order.client_order_id, "mode": active.mode.value},
            active=active,
        )
        # pragma: no mutate end
        return placed

    async def _handle_live(self, *, order, active, exchange, symbol, qty):
        try:
            placed = await exchange.place_order(order)
        except Exception as exc:  # noqa: BLE001
            self._audit_worker(
                event_type="order_place_error",
                detail={"client_order_id": order.client_order_id, "error": str(exc)},
                active=active,
                subject_id=order.client_order_id,
            )
            return None

        self._persist_order(placed=placed, active=active, symbol=symbol)
        self._audit_worker(
            event_type="order_placed",
            detail={
                "client_order_id": placed.client_order_id,
                "status": placed.status.value,
                "quantity": str(qty),
            },
            active=active,
            subject_id=placed.client_order_id,
        )

        if placed.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            if placed.status is OrderStatus.PARTIALLY_FILLED:
                self._audit_worker(
                    event_type="order_partially_filled",
                    detail={
                        "client_order_id": placed.client_order_id,
                        "quantity": str(placed.quantity),
                    },
                    active=active,
                    subject_id=placed.client_order_id,
                )
            await self._safe_notify(
                event="fill",
                detail={
                    "client_order_id": placed.client_order_id,
                    "status": placed.status.value,
                },
                active=active,
            )
        return placed

    def _persist_order(self, *, placed: Order, active, symbol) -> None:
        self._orders.upsert(
            user_id=self._user_id,
            client_order_id=placed.client_order_id,
            venue_order_id=placed.venue_order_id,
            provider=active.provider,
            mode=placed.mode.value,
            venue_symbol=symbol.venue_symbol,
            base=symbol.base,
            quote=symbol.quote,
            side=placed.side.value,
            type=placed.type.value,
            quantity=placed.quantity,
            price=placed.price,
            tif=placed.tif.value,
            status=placed.status.value,
            config_version_hash=active.version_hash,
            created_at=placed.created_at,
            updated_at=placed.updated_at,
        )

    def _record_fill(
        self,
        *,
        placed: Order,
        active,
        symbol,
        fill_id_prefix: str = "dry_run_",
        cost: CostEstimate | None = None,
    ) -> None:
        """Persist a FillRow and apply it to the position. DRY_RUN-only.

        v1: full-in/full-out — the modelled fill is the order's whole quantity at
        its price. fill_id is derived from client_order_id for idempotency, prefixed
        "dry_run_". This method's only caller is `_handle_dry_run`: TESTNET/LIVE
        fills are booked exclusively by `account_state_sync`/`ingest_fills_for_symbol`
        (the sole accounting writer for real fills, INV3) — this method never runs
        for a live/testnet order.

        Pass cost to carry the full modelled trading cost (fee + slippage + spread)
        into realized_pnl for the dry-run fill.
        """
        fee_amount = cost.total if cost is not None else Decimal("0")
        fill = Fill(
            fill_id=f"{fill_id_prefix}{placed.client_order_id}",
            client_order_id=placed.client_order_id,
            venue_order_id=placed.venue_order_id,
            symbol=symbol,
            side=placed.side,
            price=placed.price if placed.price is not None else Decimal("0"),
            quantity=placed.quantity,
            fee=fee_amount,
            fee_currency=symbol.quote,
            ts=placed.updated_at,
        )
        self._fills.add(
            user_id=self._user_id,
            fill_id=fill.fill_id,
            client_order_id=fill.client_order_id,
            venue_order_id=fill.venue_order_id,
            provider=active.provider,
            venue_symbol=symbol.venue_symbol,
            side=fill.side.value,
            price=fill.price,
            quantity=fill.quantity,
            fee=fill.fee,
            fee_currency=fill.fee_currency,
            ts=fill.ts,
        )
        self._accounting.apply_fill(
            provider=active.provider, fill=fill, charge_fee=cost is not None
        )
