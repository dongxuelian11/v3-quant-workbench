from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

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
    Fill,
    HoldingSnapshot,
    LedgerKind,
    Order,
    PositionLedgerEntry,
    Side,
    TargetQuantityRow,
    TargetQuantityVector,
    UnsupportedCorporateActionError,
    _d,
    decimal_text,
)


class DeterministicAshareBacktestEngine:
    """Pure daily/EOD research engine. No I/O or execution adapter is present."""

    def run(self, spec: BacktestRunSpec) -> BacktestRunResult:
        if not isinstance(spec, BacktestRunSpec):
            raise TypeError("spec must be BacktestRunSpec")
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

        schedule_by_date = {}
        for item in spec.schedule:
            local_date = item.effective_at.astimezone(ZoneInfo(spec.market_timezone)).date()
            schedule_by_date.setdefault(local_date, []).append(item)

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

            events = schedule_by_date.get(session.session_date, [])
            for scheduled in events:
                if not session.is_open:
                    continue
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
                    if order.side is Side.SELL:
                        fill_qty = min(fill_qty, sellable[order.instrument_id])
                        if fill_qty == 0:
                            diagnostics.append(ExecutionDiagnostic(order.order_id, DiagnosticCode.NO_SELLABLE_QUANTITY, order.requested_quantity, 0, "T+1 sellable quantity is zero"))
                            continue
                        if fill_qty < order.requested_quantity:
                            result_code = DiagnosticCode.PARTIAL_T_PLUS_ONE
                    else:
                        if fill_qty < rule.buy_minimum_quantity:
                            diagnostics.append(ExecutionDiagnostic(order.order_id, DiagnosticCode.BELOW_BUY_LOT, order.requested_quantity, 0, "quantity is below pinned buy minimum"))
                            continue
                        while fill_qty >= rule.buy_minimum_quantity:
                            consideration = Decimal(fill_qty) * _d(order.raw_limit_price)
                            costs = spec.cost_policy.calculate(Side.BUY, consideration)
                            if consideration + costs.total <= cash:
                                break
                            fill_qty -= rule.buy_quantity_step
                        if fill_qty < rule.buy_minimum_quantity:
                            diagnostics.append(ExecutionDiagnostic(order.order_id, DiagnosticCode.PARTIAL_CASH, order.requested_quantity, 0, "insufficient cash after explicit costs"))
                            continue
                        if fill_qty < order.requested_quantity:
                            result_code = DiagnosticCode.PARTIAL_CASH

                    consideration = Decimal(fill_qty) * _d(order.raw_limit_price)
                    costs = spec.cost_policy.calculate(order.side, consideration)
                    fill_payload = {"order_id": order.order_id, "quantity": fill_qty, "raw_price": order.raw_limit_price, "costs": costs.to_wire()}
                    fill_id = "fill_sha256_" + canonical_sha256(fill_payload)
                    fill = Fill(fill_id, order.order_id, session.session_date, order.instrument_id, order.side, fill_qty, order.raw_limit_price, decimal_text(consideration, "consideration"), costs)
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
                        cash_ledger.append(CashLedgerEntry(cash_sequence, session.session_date, LedgerKind.FEE, decimal_text(-costs.total, "fee_delta"), decimal_text(cash, "cash"), fill_id))
                        cash_sequence += 1
                    position_ledger.append(PositionLedgerEntry(position_sequence, session.session_date, order.instrument_id, pos_delta, quantity[order.instrument_id], sellable[order.instrument_id], fill_id))
                    position_sequence += 1
                    diagnostics.append(ExecutionDiagnostic(order.order_id, result_code, order.requested_quantity, fill_qty, result_code.value))

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
