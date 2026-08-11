from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import ClassVar

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    meet_pair,
    propagate_downstream_ceiling,
)
from v3_backend.domain.weights import RiskAdjustedWeightVector, RuntimeIdentity
from v3_backend.provenance.canonical_hash import canonical_sha256


class BacktestContractError(ValueError):
    pass


class UnsupportedCorporateActionError(BacktestContractError):
    pass


class Board(str, Enum):
    SSE_MAIN = "SSE_MAIN"
    SSE_STAR = "SSE_STAR"
    SZSE_MAIN = "SZSE_MAIN"
    SZSE_CHINEXT = "SZSE_CHINEXT"
    BSE = "BSE"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    BONUS_OR_SPLIT = "BONUS_OR_SPLIT"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    OTHER = "OTHER"


class DiagnosticCode(str, Enum):
    FILLED = "FILLED"
    PARTIAL_CASH = "PARTIAL_CASH"
    PARTIAL_T_PLUS_ONE = "PARTIAL_T_PLUS_ONE"
    SUSPENDED = "SUSPENDED"
    NOT_TRADABLE = "NOT_TRADABLE"
    BUY_RESTRICTED = "BUY_RESTRICTED"
    LIMIT_UP_BUY_BLOCKED = "LIMIT_UP_BUY_BLOCKED"
    LIMIT_DOWN_SELL_BLOCKED = "LIMIT_DOWN_SELL_BLOCKED"
    BELOW_BUY_LOT = "BELOW_BUY_LOT"
    NO_SELLABLE_QUANTITY = "NO_SELLABLE_QUANTITY"
    UNSUPPORTED_CORPORATE_ACTION = "UNSUPPORTED_CORPORATE_ACTION"


class LedgerKind(str, Enum):
    INITIAL_CASH = "INITIAL_CASH"
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"
    CASH_DIVIDEND = "CASH_DIVIDEND"


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise BacktestContractError(f"{name} must be exact non-empty text")
    return value


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise BacktestContractError(f"{name} must be a lowercase sha256")
    return value


def decimal_text(value: str | Decimal, name: str, *, non_negative: bool = False) -> str:
    try:
        observed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise BacktestContractError(f"{name} must be an exact decimal string") from exc
    if not observed.is_finite():
        raise BacktestContractError(f"{name} must be finite")
    if non_negative and observed < 0:
        raise BacktestContractError(f"{name} must be non-negative")
    if observed == 0:
        return "0"
    normalized = format(observed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _d(value: str) -> Decimal:
    return Decimal(value)


@dataclass(frozen=True, slots=True)
class ExactInputReference:
    reference_kind: str
    source_id: str
    content_sha256: str
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        _text(self.reference_kind, "reference_kind")
        _text(self.source_id, "source_id")
        _sha(self.content_sha256, "content_sha256")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be TruthAdmissionState")
        object.__setattr__(self, "truth_admission", meet_pair(self.truth_admission, PRE_ALPHA_CEILING))

    def to_wire(self) -> dict[str, object]:
        return {
            "reference_kind": self.reference_kind,
            "source_id": self.source_id,
            "content_sha256": self.content_sha256,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class BoardTradingRule:
    board: Board
    buy_minimum_quantity: int
    buy_quantity_step: int
    normal_price_limit_rate: str
    restricted_price_limit_rate: str
    price_tick: str = "0.01"
    sell_odd_lot_in_one_order: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.board, Board):
            raise TypeError("board must be Board")
        if self.buy_minimum_quantity <= 0 or self.buy_quantity_step <= 0:
            raise BacktestContractError("buy lot quantities must be positive")
        for field_name in (
            "normal_price_limit_rate",
            "restricted_price_limit_rate",
            "price_tick",
        ):
            object.__setattr__(
                self,
                field_name,
                decimal_text(getattr(self, field_name), field_name, non_negative=True),
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "board": self.board.value,
            "buy_minimum_quantity": self.buy_minimum_quantity,
            "buy_quantity_step": self.buy_quantity_step,
            "normal_price_limit_rate": self.normal_price_limit_rate,
            "restricted_price_limit_rate": self.restricted_price_limit_rate,
            "price_tick": self.price_tick,
            "sell_odd_lot_in_one_order": self.sell_odd_lot_in_one_order,
        }


@dataclass(frozen=True, slots=True)
class AshareTradingRuleProfileVersion:
    profile_id: str
    content_sha256: str
    profile_name: str
    effective_from: date
    effective_to: date | None
    settlement_days: int
    board_rules: tuple[BoardTradingRule, ...]
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.a_share_trading_rule_profile/1.0.0"

    @classmethod
    def create(
        cls,
        *,
        profile_name: str,
        effective_from: date,
        effective_to: date | None,
        settlement_days: int,
        board_rules: tuple[BoardTradingRule, ...],
        truth_admission: TruthAdmissionState = PRE_ALPHA_CEILING,
    ) -> AshareTradingRuleProfileVersion:
        _text(profile_name, "profile_name")
        ordered = tuple(sorted(board_rules, key=lambda item: item.board.value))
        if len(ordered) != len(Board) or {x.board for x in ordered} != set(Board):
            raise BacktestContractError("rule profile must define every supported board exactly once")
        if settlement_days != 1:
            raise BacktestContractError("V0 A-share core requires pinned T+1 settlement")
        if effective_to is not None and effective_to < effective_from:
            raise BacktestContractError("rule profile effective range is invalid")
        payload = {
            "schema_version": cls.schema_version,
            "profile_name": profile_name,
            "effective_from": effective_from.isoformat(),
            "effective_to": effective_to.isoformat() if effective_to else None,
            "settlement_days": settlement_days,
            "board_rules": [item.to_wire() for item in ordered],
            "truth_admission": truth_admission.to_wire(),
        }
        digest = canonical_sha256(payload)
        return cls("atrp_sha256_" + digest, digest, profile_name, effective_from, effective_to, settlement_days, ordered, truth_admission)

    def rule_for(self, board: Board) -> BoardTradingRule:
        return next(item for item in self.board_rules if item.board is board)

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "content_sha256": self.content_sha256,
            "profile_name": self.profile_name,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "settlement_days": self.settlement_days,
            "board_rules": [item.to_wire() for item in self.board_rules],
            "truth_admission": self.truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            profile_name=self.profile_name,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            settlement_days=self.settlement_days,
            board_rules=self.board_rules,
            truth_admission=self.truth_admission,
        )
        if rebuilt != self:
            raise BacktestContractError("rule profile identity/content mismatch")


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    commission: str
    stamp_duty: str
    transfer_fee: str
    exchange_fee: str

    @property
    def total(self) -> Decimal:
        return sum((_d(self.commission), _d(self.stamp_duty), _d(self.transfer_fee), _d(self.exchange_fee)), Decimal(0))

    def to_wire(self) -> dict[str, str]:
        return {"commission": self.commission, "stamp_duty": self.stamp_duty, "transfer_fee": self.transfer_fee, "exchange_fee": self.exchange_fee, "total": decimal_text(self.total, "total")}


@dataclass(frozen=True, slots=True)
class CostPolicyVersion:
    policy_id: str
    content_sha256: str
    policy_name: str
    effective_from: date
    commission_rate: str
    minimum_commission: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str
    exchange_fee_rate: str
    currency_scale: int
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.a_share_cost_policy/1.0.0"

    @classmethod
    def create(
        cls,
        *,
        policy_name: str,
        effective_from: date,
        commission_rate: str,
        minimum_commission: str,
        stamp_duty_sell_rate: str,
        transfer_fee_rate: str,
        exchange_fee_rate: str,
        currency_scale: int = 2,
        truth_admission: TruthAdmissionState = PRE_ALPHA_CEILING,
    ) -> CostPolicyVersion:
        _text(policy_name, "policy_name")
        if currency_scale < 0 or currency_scale > 8:
            raise BacktestContractError("currency_scale is outside supported range")
        values = tuple(decimal_text(value, name, non_negative=True) for name, value in (
            ("commission_rate", commission_rate),
            ("minimum_commission", minimum_commission),
            ("stamp_duty_sell_rate", stamp_duty_sell_rate),
            ("transfer_fee_rate", transfer_fee_rate),
            ("exchange_fee_rate", exchange_fee_rate),
        ))
        payload = {
            "schema_version": cls.schema_version,
            "policy_name": policy_name,
            "effective_from": effective_from.isoformat(),
            "commission_rate": values[0],
            "minimum_commission": values[1],
            "stamp_duty_sell_rate": values[2],
            "transfer_fee_rate": values[3],
            "exchange_fee_rate": values[4],
            "currency_scale": currency_scale,
            "rounding": "ROUND_HALF_UP",
            "truth_admission": truth_admission.to_wire(),
        }
        digest = canonical_sha256(payload)
        return cls("cost_sha256_" + digest, digest, policy_name, effective_from, *values, currency_scale, truth_admission)

    def _money(self, value: Decimal) -> Decimal:
        from decimal import ROUND_HALF_UP
        return value.quantize(Decimal(1).scaleb(-self.currency_scale), rounding=ROUND_HALF_UP)

    def calculate(self, side: Side, consideration: Decimal) -> CostBreakdown:
        commission = self._money(max(consideration * _d(self.commission_rate), _d(self.minimum_commission))) if consideration > 0 else Decimal(0)
        stamp = self._money(consideration * _d(self.stamp_duty_sell_rate)) if side is Side.SELL else Decimal(0)
        transfer = self._money(consideration * _d(self.transfer_fee_rate))
        exchange = self._money(consideration * _d(self.exchange_fee_rate))
        return CostBreakdown(*(decimal_text(value, "fee", non_negative=True) for value in (commission, stamp, transfer, exchange)))

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "content_sha256": self.content_sha256,
            "policy_name": self.policy_name,
            "effective_from": self.effective_from.isoformat(),
            "commission_rate": self.commission_rate,
            "minimum_commission": self.minimum_commission,
            "stamp_duty_sell_rate": self.stamp_duty_sell_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "exchange_fee_rate": self.exchange_fee_rate,
            "currency_scale": self.currency_scale,
            "rounding": "ROUND_HALF_UP",
            "truth_admission": self.truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            policy_name=self.policy_name,
            effective_from=self.effective_from,
            commission_rate=self.commission_rate,
            minimum_commission=self.minimum_commission,
            stamp_duty_sell_rate=self.stamp_duty_sell_rate,
            transfer_fee_rate=self.transfer_fee_rate,
            exchange_fee_rate=self.exchange_fee_rate,
            currency_scale=self.currency_scale,
            truth_admission=self.truth_admission,
        )
        if rebuilt != self:
            raise BacktestContractError("cost policy identity/content mismatch")


@dataclass(frozen=True, slots=True)
class InstrumentDefinition:
    instrument_id: str
    board: Board

    def __post_init__(self) -> None:
        _text(self.instrument_id, "instrument_id")
        if not isinstance(self.board, Board):
            raise TypeError("board must be Board")

    def to_wire(self) -> dict[str, str]:
        return {"instrument_id": self.instrument_id, "board": self.board.value}


@dataclass(frozen=True, slots=True)
class DailyMarketState:
    instrument_id: str
    raw_open: str
    raw_close: str | None
    suspended: bool = False
    tradable: bool = True
    buy_restricted: bool = False
    restricted_security: bool = False
    at_limit_up_open: bool = False
    at_limit_down_open: bool = False
    no_price_limit_session: bool = False

    def __post_init__(self) -> None:
        _text(self.instrument_id, "instrument_id")
        object.__setattr__(self, "raw_open", decimal_text(self.raw_open, "raw_open", non_negative=True))
        if _d(self.raw_open) <= 0:
            raise BacktestContractError("raw_open must be positive")
        if self.raw_close is not None:
            object.__setattr__(self, "raw_close", decimal_text(self.raw_close, "raw_close", non_negative=True))
            if _d(self.raw_close) <= 0:
                raise BacktestContractError("raw_close must be positive")

    def to_wire(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "raw_open": self.raw_open,
            "raw_close": self.raw_close,
            "suspended": self.suspended,
            "tradable": self.tradable,
            "buy_restricted": self.buy_restricted,
            "restricted_security": self.restricted_security,
            "at_limit_up_open": self.at_limit_up_open,
            "at_limit_down_open": self.at_limit_down_open,
            "no_price_limit_session": self.no_price_limit_session,
        }


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    instrument_id: str
    ex_date: date
    action_type: CorporateActionType
    cash_per_share: str = "0"
    ratio_numerator: int = 1
    ratio_denominator: int = 1

    def __post_init__(self) -> None:
        _text(self.action_id, "action_id")
        _text(self.instrument_id, "instrument_id")
        if not isinstance(self.action_type, CorporateActionType):
            raise TypeError("action_type must be CorporateActionType")
        object.__setattr__(self, "cash_per_share", decimal_text(self.cash_per_share, "cash_per_share", non_negative=True))
        if self.ratio_numerator <= 0 or self.ratio_denominator <= 0:
            raise BacktestContractError("corporate-action ratio must be positive")

    def to_wire(self) -> dict[str, object]:
        return {"action_id": self.action_id, "instrument_id": self.instrument_id, "ex_date": self.ex_date.isoformat(), "action_type": self.action_type.value, "cash_per_share": self.cash_per_share, "ratio_numerator": self.ratio_numerator, "ratio_denominator": self.ratio_denominator}


@dataclass(frozen=True, slots=True)
class MarketSession:
    session_date: date
    is_open: bool
    states: tuple[DailyMarketState, ...]
    corporate_actions: tuple[CorporateAction, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.states, key=lambda item: item.instrument_id))
        if len({x.instrument_id for x in ordered}) != len(ordered):
            raise BacktestContractError("market session states must be unique")
        object.__setattr__(self, "states", ordered)
        object.__setattr__(self, "corporate_actions", tuple(sorted(self.corporate_actions, key=lambda item: item.action_id)))
        if any(item.ex_date != self.session_date for item in self.corporate_actions):
            raise BacktestContractError("corporate action must match session date")

    def to_wire(self) -> dict[str, object]:
        return {"session_date": self.session_date.isoformat(), "is_open": self.is_open, "states": [x.to_wire() for x in self.states], "corporate_actions": [x.to_wire() for x in self.corporate_actions]}


@dataclass(frozen=True, slots=True)
class ScheduledWeights:
    effective_at: datetime
    vector: RiskAdjustedWeightVector

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None:
            raise BacktestContractError("effective_at must be timezone-aware")
        if not isinstance(self.vector, RiskAdjustedWeightVector):
            raise TypeError("vector must be canonical RiskAdjustedWeightVector")
        self.vector.assert_canonical()

    def to_wire(self) -> dict[str, object]:
        return {"effective_at": self.effective_at, "risk_adjusted_weight_vector_id": self.vector.risk_adjusted_weight_vector_id, "content_sha256": self.vector.content_sha256}


@dataclass(frozen=True, slots=True)
class InitialHolding:
    instrument_id: str
    quantity: int
    acquired_on: date

    def __post_init__(self) -> None:
        _text(self.instrument_id, "instrument_id")
        if self.quantity <= 0:
            raise BacktestContractError("initial holding quantity must be positive")

    def to_wire(self) -> dict[str, object]:
        return {"instrument_id": self.instrument_id, "quantity": self.quantity, "acquired_on": self.acquired_on.isoformat()}


@dataclass(frozen=True, slots=True)
class BacktestRunSpec:
    run_spec_id: str
    content_sha256: str
    initial_cash: str
    initial_holdings: tuple[InitialHolding, ...]
    instruments: tuple[InstrumentDefinition, ...]
    sessions: tuple[MarketSession, ...]
    schedule: tuple[ScheduledWeights, ...]
    rule_profile: AshareTradingRuleProfileVersion
    cost_policy: CostPolicyVersion
    exact_references: tuple[ExactInputReference, ...]
    runtime_identity: RuntimeIdentity
    engine_version: str
    market_timezone: str
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.a_share_backtest_run_spec/1.0.0"

    @classmethod
    def create(cls, *, initial_cash: str, initial_holdings: tuple[InitialHolding, ...], instruments: tuple[InstrumentDefinition, ...], sessions: tuple[MarketSession, ...], schedule: tuple[ScheduledWeights, ...], rule_profile: AshareTradingRuleProfileVersion, cost_policy: CostPolicyVersion, exact_references: tuple[ExactInputReference, ...], runtime_identity: RuntimeIdentity, engine_version: str = "v3.a_share_daily_eod_engine/0.1.0", market_timezone: str = "Asia/Shanghai") -> BacktestRunSpec:
        cash = decimal_text(initial_cash, "initial_cash", non_negative=True)
        ordered_instruments = tuple(sorted(instruments, key=lambda x: x.instrument_id))
        instrument_ids = tuple(x.instrument_id for x in ordered_instruments)
        if not ordered_instruments or len(instrument_ids) != len(set(instrument_ids)):
            raise BacktestContractError("instruments must be non-empty and unique")
        ordered_sessions = tuple(sorted(sessions, key=lambda x: x.session_date))
        if not ordered_sessions or len({x.session_date for x in ordered_sessions}) != len(ordered_sessions):
            raise BacktestContractError("sessions must be non-empty and unique by date")
        ordered_schedule = tuple(sorted(schedule, key=lambda x: x.effective_at))
        if not ordered_schedule:
            raise BacktestContractError("at least one W0 weight vector is required")
        if len({item.effective_at for item in ordered_schedule}) != len(ordered_schedule):
            raise BacktestContractError("scheduled W0 effective_at values must be unique")
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(_text(market_timezone, "market_timezone"))
        except Exception as exc:
            raise BacktestContractError("market_timezone must name an installed IANA timezone") from exc
        if any(set(x.vector.source_target.source.universe_instrument_ids) != set(instrument_ids) for x in ordered_schedule):
            raise BacktestContractError("W0 exact universe must equal BacktestRunSpec instruments")
        holdings = tuple(sorted(initial_holdings, key=lambda x: x.instrument_id))
        if len({x.instrument_id for x in holdings}) != len(holdings) or any(x.instrument_id not in instrument_ids for x in holdings):
            raise BacktestContractError("initial holdings must be unique and inside exact universe")
        refs = tuple(sorted(exact_references, key=lambda x: (x.reference_kind, x.source_id)))
        kinds = {x.reference_kind for x in refs}
        required = {"SNAPSHOT", "MARKET_DATA", "TRADING_CALENDAR", "UNIVERSE", "CORPORATE_ACTIONS"}
        if required - kinds:
            raise BacktestContractError("exact references must pin snapshot, market data, calendar, universe, and corporate actions")
        rule_profile.assert_canonical()
        cost_policy.assert_canonical()
        if any(session.session_date < rule_profile.effective_from or (rule_profile.effective_to is not None and session.session_date > rule_profile.effective_to) for session in ordered_sessions):
            raise BacktestContractError("session is outside pinned rule-profile effective range")
        if any(session.session_date < cost_policy.effective_from for session in ordered_sessions):
            raise BacktestContractError("session precedes pinned cost-policy effective date")
        requirements = [UpstreamRequirement("rule:" + rule_profile.profile_id, rule_profile.truth_admission), UpstreamRequirement("cost:" + cost_policy.policy_id, cost_policy.truth_admission)]
        requirements.extend(UpstreamRequirement("ref:" + x.reference_kind + ":" + x.source_id, x.truth_admission) for x in refs)
        requirements.extend(
            UpstreamRequirement(
                "weights:" + str(index) + ":" + x.vector.risk_adjusted_weight_vector_id,
                x.vector.truth_admission,
            )
            for index, x in enumerate(ordered_schedule)
        )
        truth = propagate_downstream_ceiling(PRE_ALPHA_CEILING, requirements)
        payload = cls._payload(cash, holdings, ordered_instruments, ordered_sessions, ordered_schedule, rule_profile, cost_policy, refs, runtime_identity, engine_version, market_timezone, truth)
        digest = canonical_sha256(payload)
        return cls("btrs_sha256_" + digest, digest, cash, holdings, ordered_instruments, ordered_sessions, ordered_schedule, rule_profile, cost_policy, refs, runtime_identity, engine_version, market_timezone, truth)

    @classmethod
    def _payload(cls, cash, holdings, instruments, sessions, schedule, rule, cost, refs, runtime, engine_version, market_timezone, truth):
        return {"schema_version": cls.schema_version, "initial_cash": cash, "initial_holdings": [x.to_wire() for x in holdings], "instruments": [x.to_wire() for x in instruments], "sessions": [x.to_wire() for x in sessions], "schedule": [x.to_wire() for x in schedule], "rule_profile_id": rule.profile_id, "rule_profile_sha256": rule.content_sha256, "cost_policy_id": cost.policy_id, "cost_policy_sha256": cost.content_sha256, "exact_references": [x.to_wire() for x in refs], "runtime_identity": runtime.to_wire(), "engine_version": _text(engine_version, "engine_version"), "market_timezone": market_timezone, "execution_timing": "EFFECTIVE_SESSION_RAW_OPEN", "valuation": "RAW_EOD_CLOSE_FAIL_CLOSED", "truth_admission": truth.to_wire()}

    def to_wire(self) -> dict[str, object]:
        return {"artifact_type": "BacktestRunSpec", "run_spec_id": self.run_spec_id, "content_sha256": self.content_sha256, **self._payload(self.initial_cash, self.initial_holdings, self.instruments, self.sessions, self.schedule, self.rule_profile, self.cost_policy, self.exact_references, self.runtime_identity, self.engine_version, self.market_timezone, self.truth_admission)}


@dataclass(frozen=True, slots=True)
class TargetQuantityRow:
    instrument_id: str
    target_weight: str
    target_quantity: int
    current_quantity: int
    sellable_quantity: int
    raw_match_price: str
    unrounded_quantity: int
    residual_notional: str
    planning_code: str

    def to_wire(self) -> dict[str, object]:
        return {"instrument_id": self.instrument_id, "target_weight": self.target_weight, "target_quantity": self.target_quantity, "current_quantity": self.current_quantity, "sellable_quantity": self.sellable_quantity, "raw_match_price": self.raw_match_price, "unrounded_quantity": self.unrounded_quantity, "residual_notional": self.residual_notional, "planning_code": self.planning_code}


@dataclass(frozen=True, slots=True)
class TargetQuantityVector:
    target_quantity_vector_id: str
    content_sha256: str
    session_date: date
    source_weight_vector_id: str
    pre_trade_nav: str
    rows: tuple[TargetQuantityRow, ...]

    @classmethod
    def create(cls, session_date: date, source_weight_vector_id: str, pre_trade_nav: Decimal, rows: tuple[TargetQuantityRow, ...]):
        ordered = tuple(sorted(rows, key=lambda x: x.instrument_id))
        payload = {"session_date": session_date.isoformat(), "source_weight_vector_id": source_weight_vector_id, "pre_trade_nav": decimal_text(pre_trade_nav, "pre_trade_nav"), "rows": [x.to_wire() for x in ordered]}
        digest = canonical_sha256(payload)
        return cls("tqv_sha256_" + digest, digest, session_date, source_weight_vector_id, payload["pre_trade_nav"], ordered)

    def to_wire(self):
        return {"target_quantity_vector_id": self.target_quantity_vector_id, "content_sha256": self.content_sha256, "session_date": self.session_date.isoformat(), "source_weight_vector_id": self.source_weight_vector_id, "pre_trade_nav": self.pre_trade_nav, "rows": [x.to_wire() for x in self.rows]}


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    session_date: date
    instrument_id: str
    side: Side
    requested_quantity: int
    raw_limit_price: str
    source_target_quantity_vector_id: str

    def to_wire(self):
        return {"order_id": self.order_id, "session_date": self.session_date.isoformat(), "instrument_id": self.instrument_id, "side": self.side.value, "requested_quantity": self.requested_quantity, "raw_limit_price": self.raw_limit_price, "source_target_quantity_vector_id": self.source_target_quantity_vector_id}


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    session_date: date
    instrument_id: str
    side: Side
    quantity: int
    raw_price: str
    consideration: str
    costs: CostBreakdown

    def to_wire(self):
        return {"fill_id": self.fill_id, "order_id": self.order_id, "session_date": self.session_date.isoformat(), "instrument_id": self.instrument_id, "side": self.side.value, "quantity": self.quantity, "raw_price": self.raw_price, "consideration": self.consideration, "costs": self.costs.to_wire()}


@dataclass(frozen=True, slots=True)
class ExecutionDiagnostic:
    order_id: str
    code: DiagnosticCode
    requested_quantity: int
    filled_quantity: int
    detail: str

    def to_wire(self):
        return {"order_id": self.order_id, "code": self.code.value, "requested_quantity": self.requested_quantity, "filled_quantity": self.filled_quantity, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CashLedgerEntry:
    sequence: int
    session_date: date
    kind: LedgerKind
    amount: str
    balance_after: str
    reference_id: str

    def to_wire(self):
        return {"sequence": self.sequence, "session_date": self.session_date.isoformat(), "kind": self.kind.value, "amount": self.amount, "balance_after": self.balance_after, "reference_id": self.reference_id}


@dataclass(frozen=True, slots=True)
class PositionLedgerEntry:
    sequence: int
    session_date: date
    instrument_id: str
    quantity_delta: int
    quantity_after: int
    sellable_after: int
    reference_id: str

    def to_wire(self):
        return {"sequence": self.sequence, "session_date": self.session_date.isoformat(), "instrument_id": self.instrument_id, "quantity_delta": self.quantity_delta, "quantity_after": self.quantity_after, "sellable_after": self.sellable_after, "reference_id": self.reference_id}


@dataclass(frozen=True, slots=True)
class HoldingSnapshot:
    session_date: date
    instrument_id: str
    quantity: int
    sellable_quantity: int
    raw_close: str
    market_value: str

    def to_wire(self):
        return {"session_date": self.session_date.isoformat(), "instrument_id": self.instrument_id, "quantity": self.quantity, "sellable_quantity": self.sellable_quantity, "raw_close": self.raw_close, "market_value": self.market_value}


@dataclass(frozen=True, slots=True)
class DailyNav:
    session_date: date
    cash: str
    holdings_value: str
    nav: str

    def to_wire(self):
        return {"session_date": self.session_date.isoformat(), "cash": self.cash, "holdings_value": self.holdings_value, "nav": self.nav}


@dataclass(frozen=True, slots=True)
class BacktestRunResult:
    result_id: str
    content_sha256: str
    run_spec_id: str
    target_quantity_vectors: tuple[TargetQuantityVector, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    diagnostics: tuple[ExecutionDiagnostic, ...]
    cash_ledger: tuple[CashLedgerEntry, ...]
    position_ledger: tuple[PositionLedgerEntry, ...]
    holdings: tuple[HoldingSnapshot, ...]
    nav: tuple[DailyNav, ...]
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.a_share_backtest_result/1.0.0"

    @classmethod
    def create(cls, spec: BacktestRunSpec, target_quantity_vectors, orders, fills, diagnostics, cash_ledger, position_ledger, holdings, nav):
        payload = {"schema_version": cls.schema_version, "run_spec_id": spec.run_spec_id, "target_quantity_vectors": [x.to_wire() for x in target_quantity_vectors], "orders": [x.to_wire() for x in orders], "fills": [x.to_wire() for x in fills], "diagnostics": [x.to_wire() for x in diagnostics], "cash_ledger": [x.to_wire() for x in cash_ledger], "position_ledger": [x.to_wire() for x in position_ledger], "holdings": [x.to_wire() for x in holdings], "nav": [x.to_wire() for x in nav], "truth_admission": spec.truth_admission.to_wire()}
        digest = canonical_sha256(payload)
        return cls("btrr_sha256_" + digest, digest, spec.run_spec_id, tuple(target_quantity_vectors), tuple(orders), tuple(fills), tuple(diagnostics), tuple(cash_ledger), tuple(position_ledger), tuple(holdings), tuple(nav), spec.truth_admission)

    def to_wire(self):
        return {"artifact_type": "BacktestRunResult", "result_id": self.result_id, "content_sha256": self.content_sha256, "run_spec_id": self.run_spec_id, "target_quantity_vectors": [x.to_wire() for x in self.target_quantity_vectors], "orders": [x.to_wire() for x in self.orders], "fills": [x.to_wire() for x in self.fills], "diagnostics": [x.to_wire() for x in self.diagnostics], "cash_ledger": [x.to_wire() for x in self.cash_ledger], "position_ledger": [x.to_wire() for x in self.position_ledger], "holdings": [x.to_wire() for x in self.holdings], "nav": [x.to_wire() for x in self.nav], "truth_admission": self.truth_admission.to_wire()}


def cn_a_share_2026_07_06_rule_profile() -> AshareTradingRuleProfileVersion:
    return AshareTradingRuleProfileVersion.create(
        profile_name="CN_A_SHARE_2026_07_06_V1",
        effective_from=date(2026, 7, 6),
        effective_to=None,
        settlement_days=1,
        board_rules=(
            BoardTradingRule(Board.SSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SSE_STAR, 200, 1, "0.20", "0.20"),
            BoardTradingRule(Board.SZSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SZSE_CHINEXT, 100, 100, "0.20", "0.20"),
            BoardTradingRule(Board.BSE, 100, 1, "0.30", "0.30"),
        ),
    )


OrderIntent = Order
BacktestOrder = Order


__all__ = [
    "AshareTradingRuleProfileVersion",
    "BacktestContractError",
    "BacktestOrder",
    "BacktestRunResult",
    "BacktestRunSpec",
    "Board",
    "BoardTradingRule",
    "CashLedgerEntry",
    "CorporateAction",
    "CorporateActionType",
    "CostBreakdown",
    "CostPolicyVersion",
    "DailyMarketState",
    "DailyNav",
    "DiagnosticCode",
    "ExactInputReference",
    "ExecutionDiagnostic",
    "Fill",
    "HoldingSnapshot",
    "InitialHolding",
    "InstrumentDefinition",
    "LedgerKind",
    "MarketSession",
    "Order",
    "OrderIntent",
    "PositionLedgerEntry",
    "ScheduledWeights",
    "Side",
    "TargetQuantityRow",
    "TargetQuantityVector",
    "UnsupportedCorporateActionError",
    "cn_a_share_2026_07_06_rule_profile",
]
