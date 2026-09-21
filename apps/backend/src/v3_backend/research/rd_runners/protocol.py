"""Small file handshake with the Windows owner; no credentials in this state."""
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_bridge = None
_config = None


def initialize(path):
    global _bridge, _config
    _bridge = Path(path).resolve()
    _config = json.loads((_bridge / 'config.json').read_text(encoding='utf-8-sig'))
    if not 1 <= int(_config.get('rounds', 1)) <= 3:
        raise ValueError('研究轮数必须在1至3之间')
    if not 1 <= int(_config.get('codeRepairRounds', 3)) <= 3:
        raise ValueError('代码修复次数必须在1至3之间')
    if _config.get('action') not in {'factor', 'model', 'joint'}:
        raise ValueError('原生Quant仅支持factor/model/joint')
    return _config


def config():
    if _config is None:
        raise RuntimeError('尚未初始化研究桥')
    return _config


def bridge():
    config()
    return _bridge


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def event(kind, **fields):
    payload = {'id': uuid.uuid4().hex, 'time': datetime.now(timezone.utc).isoformat(), 'event': kind, **fields}
    with (bridge() / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + '\n')


def evaluate(request, request_id=None):
    """Publish completed artifacts, then wait for the owner's real evaluation."""
    identifier = request_id or uuid.uuid4().hex
    folder = bridge() / 'evaluations' / identifier
    folder.mkdir(parents=True, exist_ok=True)
    request_path = folder / 'request.json'
    if not request_path.exists():
        write_json(request_path, {'id': identifier, **request})
    event('evaluation_waiting', evaluationId=identifier, action=request['action'])
    deadline = time.monotonic() + float(config().get('evaluationTimeoutSeconds', 7200))
    while not (folder / 'response.json').is_file():
        if (bridge() / 'cancel.json').exists():
            raise InterruptedError('研究任务已取消')
        if time.monotonic() >= deadline:
            raise TimeoutError('等待V3真实评价超时；请求与产物已保留')
        time.sleep(.3)
    response = json.loads((folder / 'response.json').read_text(encoding='utf-8-sig'))
    if response.get('error'):
        raise ValueError('V3评价失败: ' + str(response['error']))
    event('evaluation_completed', evaluationId=identifier, candidateId=response.get('candidateId'),
          experimentIds=response.get('experimentIds', []))
    return response


def native_metrics(response):
    import pandas as pd
    required = ['IC', '1day.excess_return_with_cost.annualized_return', '1day.excess_return_with_cost.max_drawdown']
    values = response.get('metrics', {})
    for name in required:
        if name not in values or not isinstance(values[name], (int, float)) or not math.isfinite(values[name]):
            raise ValueError('原生反馈缺少真实验证指标: ' + name)
    # Upstream factor process_results expects the literal column name "0".
    result=pd.DataFrame({'0': {key: value for key, value in values.items()
                              if isinstance(value, (int, float)) and math.isfinite(value)}})
    # Native history prompts index these gross-return rows explicitly. Older
    # checkpoints did not retain them: NaN means unavailable, never net-as-gross.
    for key in ('1day.excess_return_without_cost.annualized_return','1day.excess_return_without_cost.max_drawdown'):
        if key not in result.index: result.loc[key,'0']=float('nan')
    return result


def reserve(category,count=1,operation_id=None):
    from ..ai_budget import BudgetExhausted
    cfg=config()
    if not cfg.get('budgetId'):raise ValueError('原生研究缺少方案预算')
    folder=bridge()/'budgetRequests'/uuid.uuid4().hex
    write_json(folder/'request.json',dict(category=category,count=count,operationId=operation_id))
    deadline=time.monotonic()+120
    while not (folder/'response.json').is_file():
        if (bridge()/'cancel.json').exists():raise InterruptedError('研究任务已取消')
        if time.monotonic()>deadline:raise TimeoutError('等待预算许可超时，未发送额外模型请求')
        time.sleep(.05)
    response=json.loads((folder/'response.json').read_text(encoding='utf-8'))
    if not response.get('allowed'):
        error=BudgetExhausted if response.get('errorType')=='BudgetExhausted' else ValueError
        raise error(response.get('error','预算许可失败'))
    result=response['budget']
    event('budget_reserved',category=category,count=count,used=result['used'],limits=result['limits'])
    return result
