"""Immutable declarative-rule observations, streamed a trading day at a time.

`date` is the signal date. Order fields describe the security's net order, not
an order owned by one rule. Constraint reasons apply to the whole decision.
A short-circuited condition is not_evaluated, never retroactively inferred.
"""
import json
import math
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def pending_condition(index, condition):
    definition = condition if isinstance(condition, dict) else {}
    threshold = definition.get('value')
    # Invalid but short-circuited numeric thresholds must not turn observation into execution.
    special = isinstance(threshold, (int, float)) and not math.isfinite(threshold)
    return dict(conditionIndex=index, field=definition.get('field'), op=definition.get('op'),
                threshold=None if special else threshold,
                thresholdState='missing' if threshold is None else ('missing' if pd.isna(threshold) else
                                'positive_infinity' if threshold > 0 else 'negative_infinity') if special else 'present',
                value=None, valueState='not_evaluated', conditionState='not_evaluated')


def execution_table(rows, kind):
    frame = pd.DataFrame(rows)
    if not rows:
        columns = ['date', 'signalDate', 'symbol', 'orderId']
        columns += ['tradeId', 'direction', 'amount', 'price', 'value', 'cost', 'reason'] if kind == 'trades' else [
            'side', 'requestedQuantity', 'allowedQuantity', 'reason']
        frame = pd.DataFrame({name:pd.Series(dtype='object') for name in columns})
    return frame


def condition_value(value):
    if value is None or pd.isna(value):
        return None, 'missing'
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isinf(value):
            return None, 'positive_infinity' if value > 0 else 'negative_infinity'
    return value, 'present'


SCHEMA = pa.schema([
    (name, pa.string()) for name in
    ('date', 'executionDate', 'symbol', 'ruleId', 'action', 'ruleState', 'skipReason')
] + [('ruleIndex', pa.int32()), ('beforeWeight', pa.float64()), ('targetWeight', pa.float64())] + [
    (name, pa.string()) for name in
    ('conditionsJson', 'constraintReasonsJson', 'orderId', 'orderState', 'orderReasonsJson')
] + [('requestedQuantity', pa.float64()), ('filledQuantity', pa.float64())])


class Writer:
    """Publish only after close succeeds; retain a .writing file on failure."""
    def __init__(self, output):
        self.path = Path(output) / 'rule_diagnostics.parquet'
        self.temporary = self.path.with_suffix('.writing.parquet')
        self.rows = 0
        self.complete = False
        self.writer = None

    def __enter__(self):
        self.writer = pq.ParquetWriter(self.temporary, SCHEMA, compression='snappy')
        return self

    def write_day(self, decision, result, execution_date):
        orders = {row['symbol']: row for row in result.get('_diagnosticOrders', [])}
        buffer = []
        for observation in decision.get('ruleDiagnostics', []):
            order = orders.get(observation['symbol'])
            row = {**observation, 'executionDate': str(pd.Timestamp(execution_date).date()),
                   'constraintReasonsJson': json_text(decision['conflicts']),
                   'orderId': order['orderId'] if order else None,
                   'orderState': order['state'] if order else 'no_order',
                   'requestedQuantity': order['requestedQuantity'] if order else 0.,
                   'filledQuantity': order['filledQuantity'] if order else 0.,
                   'orderReasonsJson': json_text(order['reasons'] if order else ['未形成净调仓订单'])}
            row['conditionsJson'] = json_text(row.pop('conditions'))
            buffer.append(row)
            if len(buffer) == 8192:
                self._write(buffer)
                buffer = []
        if buffer:
            self._write(buffer)

    def _write(self, rows):
        self.writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
        self.rows += len(rows)

    def __exit__(self, exc_type, exc, traceback):
        self.writer.close()
        if exc_type is None:
            self.temporary.replace(self.path)
            self.complete = True

    def artifact(self):
        if not self.complete:
            raise ValueError('条件诊断尚未完整保存')
        return dict(name='rule_diagnostics', path=str(self.path), type='parquet')

    def capability(self):
        self.artifact()
        return dict(version=1, status='available', artifact='rule_diagnostics', rowCount=self.rows,
                    scope='declarative_backtest_rules', dateBasis='signal_date')
