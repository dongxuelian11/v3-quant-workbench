from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from v3_backend.provenance.canonical_hash import canonical_sha256

from .model import (
    BacktestContractError,
    BacktestRunResult,
    BacktestRunSpec,
    CashLedgerEntry,
    CorporateActionType,
    DailyNav,
    DiagnosticCode,
    ExecutionDiagnostic,
    ExpiredScheduledWeightsError,
    Fill,
    HoldingSnapshot,
    LedgerKind,
    Order,
    PositionLedgerEntry,
    ResearchExecutionInputs,
    ResearchExecutionProfileV1,
    Side,
    TargetQuantityRow,
    TargetQuantityVector,
    UnsupportedCorporateActionError,
    _d,
    decimal_text,
)


class DeterministicAshareBacktestEngine:
    """Pure daily/EOD research engine. No I/O or execution adapter is present."""

    legacy_engine_version = "v3.a_share_daily_eod_engine/0.2.0"
    research_engine_version = "v3.a_share_daily_eod_engine/0.3.0-research"

    @classmethod
    def _validate_execution_inputs(
        cls,
        spec: BacktestRunSpec,
        research_execution: ResearchExecutionInputs | None,
    ) -> tuple[
        ResearchExecutionProfileV1 | None,
        dict[tuple[object, str], int],
    ]:
        if spec.engine_version == cls.legacy_engine_version:
            if research_execution is not None:
                raise BacktestContractError(
                    "legacy engine does not accept research execution inputs"
                )
            return None, {}
        if spec.engine_version != cls.research_engine_version:
            raise BacktestContractError("unsupported backtest engine version")
        if not isinstance(research_execution, ResearchExecutionInputs):
            raise BacktestContractError(
                "research engine requires research execution inputs"
            )
        research_execution.assert_canonical()

        policy_refs = tuple(
            item
            for item in spec.exact_references
            if item.reference_kind == "RESEARCH_EXECUTION_POLICY"
        )
        if len(policy_refs) != 1 or (
            policy_refs[0].source_id != research_execution.profile.profile_id
            or policy_refs[0].content_sha256
            != research_execution.profile.content_sha256
            or policy_refs[0].truth_admission
            != research_execution.profile.truth_admission
        ):
            raise BacktestContractError(
                "research execution policy binding does not match exact reference"
            )

        market_refs = tuple(
            item
            for item in spec.exact_references
            if item.reference_kind == "MARKET_DATA"
        )
        if len(market_refs) != 1 or (
            market_refs[0].source_id
            != research_execution.market_data_source_id
            or market_refs[0].content_sha256
            != research_execution.market_data_content_sha256
        ):
            raise BacktestContractError(
                "research market payload binding does not match exact reference"
            )

        liquidity = {
            (row.session_date, row.instrument_id): row.volume_shares
            for row in research_execution.liquidity_rows
        }
        expected_keys = {
            (session.session_date, instrument.instrument_id)
            for session in spec.sessions
            for instrument in spec.instruments
        }
        if set(liquidity) != expected_keys:
            raise BacktestContractError(
                "research liquidity payload must exactly cover run sessions and instruments"
            )
        return research_execution.profile, liquidity

    @staticmethod
    def _execution_price(
        raw_price: str,
        side: Side,
        profile: ResearchExecutionProfileV1,
        price_tick: str,
    ) -> Decimal:
        raw = _d(raw_price)
        tick = _d(price_tick)
        if tick <= 0:
            raise BacktestContractError("price_tick must be positive")
        slip = _d(profile.slippage_bps) / Decimal("10000")
        adjusted = raw * (Decimal(1) + slip if side is Side.BUY else Decimal(1) - slip)
        if adjusted <= 0:
            raise BacktestContractError("slippage-adjusted execution price must be positive")
        rounding = ROUND_CEILING if side is Side.BUY else ROUND_FLOOR
        tick_units = (adjusted / tick).to_integral_value(rounding=rounding)
        return tick_units * tick

    @staticmethod
    def _participation_cap(
        *,
        requested_quantity: int,
        volume_shares: int,
        participation_rate: str,
        side: Side,
        buy_minimum_quantity: int,
        buy_quantity_step: int,
        sell_odd_lot_in_one_order: bool,
    ) -> int:
        raw_cap = int(
            (Decimal(volume_shares) * _d(participation_rate)).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        if side is Side.BUY:
            if raw_cap < buy_minimum_quantity:
                return 0
            return buy_minimum_quantity + (
                (raw_cap - buy_minimum_quantity) // buy_quantity_step
            ) * buy_quantity_step
        if sell_odd_lot_in_one_order and requested_quantity <= raw_cap:
            return requested_quantity
        return (raw_cap // buy_quantity_step) * buy_quantity_step

    @staticmethod
    def _max_affordable_buy_quantity(
        *,
        candidate_quantity: int,
        minimum_quantity: int,
        quantity_step: int,
        execution_price: Decimal,
        cash: Decimal,
        cost_policy,
        board,
        session_date,
    ) -> int:
        if candidate_quantity < minimum_quantity:
            return 0
        lowest_quantity = candidate_quantity - (
            (candidate_quantity - minimum_quantity) // quantity_step
        ) * quantity_step
        low_index = 0
        high_index = (candidate_quantity - lowest_quantity) // quantity_step
        best_quantity = 0
        while low_index <= high_index:
            middle = (low_index + high_index) // 2
            quantity = lowest_quantity + middle * quantity_step
            consideration = Decimal(quantity) * execution_price
            costs = cost_policy.calculate(
                board, Side.BUY, consideration, session_date
            )
            if consideration + costs.total <= cash:
                best_quantity = quantity
                low_index = middle + 1
            else:
                high_index = middle - 1
        return best_quantity

    def run(
        self,
        spec: BacktestRunSpec,
        *,
        research_execution: ResearchExecutionInputs | None = None,
    ) -> BacktestRunResult:
        if not isinstance(spec, BacktestRunSpec):
            raise TypeError("spec must be BacktestRunSpec")
        research_profile, liquidity = self._validate_execution_inputs(
            spec, research_execution
        )
        instrument_map = {item.instrument_id: item for item in spec.instruments}
        first_date = spec.sessions[0].session_date
        quantity = {item.instrument_id: 0 for item in spec.instruments}
        sellable = {item.instrument_id: 0 for item in spec.instruments}
        acquired_today = {item.instrument_id: 0 for item in spec.instruments}
        acquired_on = {}
        for item in spec.initial_holdings:
            quantity[item.instrument_id] = item.quantity
            acquired_on[item.instrument_id] = item.acquired_on
            if item.acquired_on >= first_date:
                acquired_today[item.instrument_id] = item.quantity

        cash = _d(spec.initial_cash)
        target_vectors = []
        orders = []
        fills = []
        diagnostics = []
        cash_ledger = []
        position_ledger = []
        holdings = []
        nav_rows = []
        cash_sequence = 1
        position_sequence = 1
        cash_ledger.append(CashLedgerEntry(cash_sequence, first_date, LedgerKind.INITIAL_CASH, spec.initial_cash, spec.initial_cash, spec.run_spec_id))
        cash_sequence += 1

        pending_schedule = list(spec.schedule)

        for session in spec.sessions:
            state_map = {item.instrument_id: item for item in session.states}
            if set(state_map) != set(instrument_map):
                raise BacktestContractError("every session must provide every exact-universe instrument state")

            if session.is_open:
                for instrument_id in quantity:
                    previous = acquired_on.get(instrument_id)
                    sellable[instrument_id] = quantity[instrument_id] if previous is None or previous < session.session_date else quantity[instrument_id] - acquired_today[instrument_id]
                    acquired_today[instrument_id] = 0

            for action in session.corporate_actions:
                if action.action_type is CorporateActionType.CASH_DIVIDEND:
                    amount = Decimal(quantity[action.instrument_id]) * _d(action.cash_per_share)
                    cash += amount
                    cash_ledger.append(CashLedgerEntry(cash_sequence, session.session_date, LedgerKind.CASH_DIVIDEND, decimal_text(amount, "dividend"), decimal_text(cash, "cash"), action.action_id))
                    cash_sequence += 1
                elif action.action_type is CorporateActionType.BONUS_OR_SPLIT:
                    numerator = quantity[action.instrument_id] * action.ratio_numerator
                    sellable_numerator = sellable[action.instrument_id] * action.ratio_numerator
                    if numerator % action.ratio_denominator or sellable_numerator % action.ratio_denominator:
                        raise UnsupportedCorporateActionError("fractional corporate-action entitlement is NOT_SUPPORTED")
                    old = quantity[action.instrument_id]
                    quantity[action.instrument_id] = numerator // action.ratio_denominator
                    sellable[action.instrument_id] = sellable_numerator // action.ratio_denominator
                    position_ledger.append(PositionLedgerEntry(position_sequence, session.session_date, action.instrument_id, quantity[action.instrument_id] - old, quantity[action.instrument_id], sellable[action.instrument_id], action.action_id))
                    position_sequence += 1
                else:
                    raise UnsupportedCorporateActionError(f"{action.action_type.value} is NOT_SUPPORTED")

            events = []
            if session.is_open:
                cutoff = spec.execution_timing_profile.eligibility_cutoff(session.session_date)
                eligible_count = 0
                for item in pending_schedule:
                    if item.effective_at < cutoff:
                        eligible_count += 1
                    else:
                        break
                if eligible_count:
                    scheduled = pending_schedule[eligible_count - 1]
                    pending_schedule = pending_schedule[eligible_count:]
                    execution_timestamp = spec.execution_timing_profile.execution_timestamp(session.session_date)
                    if execution_timestamp > scheduled.vector.source_target.valid_until:
                        raise ExpiredScheduledWeightsError(
                            "selected W0 vector expires before raw-open execution timestamp"
                        )
                    events.append(scheduled)

            for scheduled in events:
                pre_trade_nav = cash + sum(Decimal(quantity[i]) * _d(state_map[i].raw_open) for i in quantity)
                weights = {row.instrument_id: _d(row.target_weight) for row in scheduled.vector.rows}
                rows = []
                for instrument_id in sorted(quantity):
                    state = state_map[instrument_id]
                    rule = spec.rule_profile.rule_for(instrument_map[instrument_id].board)
                    weight = weights.get(instrument_id, Decimal(0))
                    raw_target = int((pre_trade_nav * weight / _d(state.raw_open)).to_integral_value(rounding="ROUND_FLOOR"))
                    if raw_target < rule.buy_minimum_quantity:
                        target = 0
                    else:
                        target = rule.buy_minimum_quantity + ((raw_target - rule.buy_minimum_quantity) // rule.buy_quantity_step) * rule.buy_quantity_step
                    residual = pre_trade_nav * weight - Decimal(target) * _d(state.raw_open)
                    planning_code = "EXACT" if residual == 0 else ("BELOW_BUY_LOT" if target == 0 and weight > 0 else "LOT_ROUNDED_RESIDUAL")
                    rows.append(TargetQuantityRow(instrument_id, decimal_text(weight, "weight"), target, quantity[instrument_id], sellable[instrument_id], state.raw_open, raw_target, decimal_text(residual, "residual_notional", non_negative=True), planning_code))
                target_vector = TargetQuantityVector.create(session.session_date, scheduled.vector.risk_adjusted_weight_vector_id, pre_trade_nav, tuple(rows))
                target_vectors.append(target_vector)

                planned = []
                for row in rows:
                    delta = row.target_quantity - row.current_quantity
                    if delta:
                        side = Side.BUY if delta > 0 else Side.SELL
                        requested = abs(delta)
                        order_payload = {"session_date": session.session_date.isoformat(), "instrument_id": row.instrument_id, "side": side.value, "requested_quantity": requested, "raw_limit_price": row.raw_match_price, "source_target_quantity_vector_id": target_vector.target_quantity_vector_id}
                        order_id = "order_sha256_" + canonical_sha256(order_payload)
                        planned.append(Order(order_id, session.session_date, row.instrument_id, side, requested, row.raw_match_price, target_vector.target_quantity_vector_id))
                planned.sort(key=lambda item: (0 if item.side is Side.SELL else 1, item.instrument_id))

                for order in planned:
                    orders.append(order)
                    state = state_map[order.instrument_id]
                    rule = spec.rule_profile.rule_for(instrument_map[order.instrument_id].board)
                    blocking = None
                    if state.suspended:
                        blocking = DiagnosticCode.SUSPENDED
                    elif not state.tradable:
                        blocking = DiagnosticCode.NOT_TRADABLE
                    elif order.side is Side.BUY and state.buy_restricted:
                        blocking = DiagnosticCode.BUY_RESTRICTED
                    elif order.side is Side.BUY and state.at_limit_up_open and not state.no_price_limit_session:
                        blocking = DiagnosticCode.LIMIT_UP_BUY_BLOCKED
                    elif order.side is Side.SELL and state.at_limit_down_open and not state.no_price_limit_session:
                        blocking = DiagnosticCode.LIMIT_DOWN_SELL_BLOCKED
                    if blocking:
                        diagnostics.append(ExecutionDiagnostic(order.order_id, blocking, order.requested_quantity, 0, blocking.value))
                        continue

                    fill_qty = order.requested_quantity
                    result_code = DiagnosticCode.FILLED
                    participation_cap = None
                    eligible_quantity = None
                    execution_price = _d(order.raw_limit_price)
                    if research_profile is not None:
                        participation_cap = self._participation_cap(
                            requested_quantity=order.requested_quantity,
                            volume_shares=liquidity[
                                (session.session_date, order.instrument_id)
                            ],
                            participation_rate=research_profile.daily_volume_participation_rate,
                            side=order.side,
                            buy_minimum_quantity=rule.buy_minimum_quantity,
                            buy_quantity_step=rule.buy_quantity_step,
                            sell_odd_lot_in_one_order=rule.sell_odd_lot_in_one_order,
                        )
                        if participation_cap == 0:
                            diagnostics.append(
                                ExecutionDiagnostic(
                                    order.order_id,
                                    DiagnosticCode.NO_MARKET_VOLUME,
                                    order.requested_quantity,
                                    0,
                                    "admitted volume participation cap is below an executable lot",
                                    0,
                                    order.requested_quantity,
                                    0,
                                )
                            )
                            continue
                        fill_qty = min(fill_qty, participation_cap)
                        if fill_qty < order.requested_quantity:
                            result_code = DiagnosticCode.PARTIAL_VOLUME
                        execution_price = self._execution_price(
                            order.raw_limit_price,
                            order.side,
                            research_profile,
                            rule.price_tick,
                        )
                    if order.side is Side.SELL:
                        before_sellable = fill_qty
                        fill_qty = min(fill_qty, sellable[order.instrument_id])
                        if fill_qty == 0:
                            diagnostics.append(
                                ExecutionDiagnostic(
                                    order.order_id,
                                    DiagnosticCode.NO_SELLABLE_QUANTITY,
                                    order.requested_quantity,
                                    0,
                                    "T+1 sellable quantity is zero",
                                    0 if research_profile is not None else None,
                                    order.requested_quantity if research_profile is not None else None,
                                    participation_cap,
                                )
                            )
                            continue
                        if fill_qty < before_sellable:
                            result_code = DiagnosticCode.PARTIAL_T_PLUS_ONE
                        if research_profile is not None:
                            eligible_quantity = fill_qty
                    else:
                        if order.requested_quantity < rule.buy_minimum_quantity:
                            diagnostics.append(
                                ExecutionDiagnostic(
                                    order.order_id,
                                    DiagnosticCode.BELOW_BUY_LOT,
                                    order.requested_quantity,
                                    0,
                                    "quantity is below pinned buy minimum",
                                    0 if research_profile is not None else None,
                                    order.requested_quantity if research_profile is not None else None,
                                    participation_cap,
                                )
                            )
                            continue
                        if research_profile is not None:
                            eligible_quantity = fill_qty
                        fill_qty = self._max_affordable_buy_quantity(
                            candidate_quantity=fill_qty,
                            minimum_quantity=rule.buy_minimum_quantity,
                            quantity_step=rule.buy_quantity_step,
                            execution_price=execution_price,
                            cash=cash,
                            cost_policy=spec.cost_policy,
                            board=instrument_map[order.instrument_id].board,
                            session_date=session.session_date,
                        )
                        if fill_qty < rule.buy_minimum_quantity:
                            diagnostics.append(
                                ExecutionDiagnostic(
                                    order.order_id,
                                    DiagnosticCode.PARTIAL_CASH,
                                    order.requested_quantity,
                                    0,
                                    "insufficient cash after explicit costs",
                                    eligible_quantity,
                                    order.requested_quantity if research_profile is not None else None,
                                    participation_cap,
                                )
                            )
                            continue
                        if eligible_quantity is not None and fill_qty < eligible_quantity:
                            result_code = DiagnosticCode.PARTIAL_CASH
                        elif research_profile is None and fill_qty < order.requested_quantity:
                            result_code = DiagnosticCode.PARTIAL_CASH

                    consideration = Decimal(fill_qty) * execution_price
                    costs = spec.cost_policy.calculate(instrument_map[order.instrument_id].board, order.side, consideration, session.session_date)
                    fill_payload = {"order_id": order.order_id, "quantity": fill_qty, "raw_price": order.raw_limit_price, "costs": costs.to_wire()}
                    if research_profile is not None:
                        fill_payload.update(
                            {
                                "execution_price": decimal_text(
                                    execution_price, "execution_price"
                                ),
                                "participation_cap": participation_cap,
                                "slippage_bps": research_profile.slippage_bps,
                            }
                        )
                    fill_id = "fill_sha256_" + canonical_sha256(fill_payload)
                    fill = Fill(
                        fill_id,
                        order.order_id,
                        session.session_date,
                        order.instrument_id,
                        order.side,
                        fill_qty,
                        order.raw_limit_price,
                        decimal_text(consideration, "consideration"),
                        costs,
                        decimal_text(execution_price, "execution_price")
                        if research_profile is not None
                        else None,
                        participation_cap,
                        research_profile.slippage_bps
                        if research_profile is not None
                        else None,
                    )
                    fills.append(fill)
                    if order.side is Side.BUY:
                        cash -= consideration
                        quantity[order.instrument_id] += fill_qty
                        acquired_today[order.instrument_id] += fill_qty
                        acquired_on[order.instrument_id] = session.session_date
                        cash_amount = -consideration
                        pos_delta = fill_qty
                    else:
                        cash += consideration
                        quantity[order.instrument_id] -= fill_qty
                        sellable[order.instrument_id] -= fill_qty
                        cash_amount = consideration
                        pos_delta = -fill_qty
                    cash_ledger.append(CashLedgerEntry(cash_sequence, session.session_date, LedgerKind.BUY if order.side is Side.BUY else LedgerKind.SELL, decimal_text(cash_amount, "cash_delta"), decimal_text(cash, "cash"), fill_id))
                    cash_sequence += 1
                    if costs.total:
                        cash -= costs.total
                        cash_ledger.append(CashLedgerEntry(cash_sequence, session.session_date, LedgerKind.FEE, decimal_text(-costs.total, "fee_delta"), decimal_text(cash, "cash"), fill_id, costs))
                        cash_sequence += 1
                    position_ledger.append(PositionLedgerEntry(position_sequence, session.session_date, order.instrument_id, pos_delta, quantity[order.instrument_id], sellable[order.instrument_id], fill_id))
                    position_sequence += 1
                    diagnostics.append(
                        ExecutionDiagnostic(
                            order.order_id,
                            result_code,
                            order.requested_quantity,
                            fill_qty,
                            result_code.value,
                            eligible_quantity,
                            order.requested_quantity - fill_qty
                            if research_profile is not None
                            else None,
                            participation_cap,
                        )
                    )

            holdings_value = Decimal(0)
            for instrument_id in sorted(quantity):
                if quantity[instrument_id] == 0:
                    continue
                close = state_map[instrument_id].raw_close
                if close is None:
                    raise BacktestContractError("RAW_EOD_CLOSE_FAIL_CLOSED: missing close price")
                value = Decimal(quantity[instrument_id]) * _d(close)
                holdings_value += value
                holdings.append(HoldingSnapshot(session.session_date, instrument_id, quantity[instrument_id], sellable[instrument_id], close, decimal_text(value, "market_value")))
            nav_rows.append(DailyNav(session.session_date, decimal_text(cash, "cash"), decimal_text(holdings_value, "holdings_value"), decimal_text(cash + holdings_value, "nav")))

        return BacktestRunResult.create(spec, target_vectors, orders, fills, diagnostics, cash_ledger, position_ledger, holdings, nav_rows)
