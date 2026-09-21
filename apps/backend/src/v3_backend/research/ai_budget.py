"""Count outgoing model requests before transport, including failed attempts."""
from copy import deepcopy
from contextlib import contextmanager


class BudgetExhausted(ValueError):
    pass


def model_budget(previous=None):
    return deepcopy(previous) if previous else {'limit': 30, 'used': 0, 'scope': 'execution'}


def consume_model_request(execution):
    budget = execution.setdefault('modelBudget', model_budget())
    if budget['used'] >= budget['limit']:
        raise BudgetExhausted(f"模型请求已达本次研究上限 {budget['limit']} 次；已保留结果，未发送额外请求。")
    budget['used'] += 1


def budget_failure(error):
    # SDKs may wrap a request-hook exception as a connection error.
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, BudgetExhausted):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


DEFAULT_LIMITS={'modelRequests':30,'trials':20,'candidateGroups':6}
CATEGORIES=set(DEFAULT_LIMITS)|{'trainingTasks','backtestTasks','rollingWindows','codeAttempts'}


@contextmanager
def _database(db_path):
    import sqlite3
    from pathlib import Path
    path=Path(db_path)
    if not path.is_file():raise ValueError('研究预算数据库不存在，不能创建空白预算绕过历史')
    connection=sqlite3.connect(path,timeout=30)
    try:
        with connection:yield connection
    finally:connection.close()


def _stamp():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()


def ensure_budget(db_path,budget_id,limits=None):
    import json,re
    if not isinstance(budget_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',budget_id):raise ValueError('研究预算ID无效')
    selected={**DEFAULT_LIMITS,**(limits or {})}
    if any(k not in DEFAULT_LIMITS or type(v) is not int or not 1<=v<=DEFAULT_LIMITS[k] for k,v in selected.items()):
        raise ValueError('研究预算不得超过30模型请求、20试参、6组候选')
    with _database(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT body FROM records WHERE kind='research_budget' AND id=?",(budget_id,)).fetchone()
        if row:
            value=json.loads(row[0])
            if limits is not None and value['limits']!=selected:raise ValueError('既有方案预算不能在恢复时更改')
            return value
        value=dict(id=budget_id,scope='research_plan',limits=selected,used={k:0 for k in DEFAULT_LIMITS},operations={},updatedAt=_stamp())
        db.execute('INSERT INTO records(kind,id,project,body) VALUES(?,?,?,?)',('research_budget',budget_id,None,json.dumps(value,ensure_ascii=False)))
        return value


def read_budget(db_path,budget_id):
    import json
    with _database(db_path) as db:
        row=db.execute("SELECT body FROM records WHERE kind='research_budget' AND id=?",(budget_id,)).fetchone()
    if not row:raise ValueError('研究预算记录缺失，不能重置后继续')
    return json.loads(row[0])


def reserve(db_path,budget_id,category,count=1,operation_id=None):
    import json
    if category not in CATEGORIES or type(count) is not int or count<0:raise ValueError('研究预算类别或数量无效')
    if operation_id is not None and (not isinstance(operation_id,str) or not operation_id or len(operation_id)>250):raise ValueError('计算登记ID无效')
    with _database(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT body FROM records WHERE kind='research_budget' AND id=?",(budget_id,)).fetchone()
        if not row:raise ValueError('研究预算记录缺失，不能重置后继续')
        value=json.loads(row[0]);operation=dict(category=category,count=count)
        if operation_id is not None and operation_id in value['operations']:
            if value['operations'][operation_id]!=operation:raise ValueError('计算登记ID与原预留不一致')
            return value
        used=value['used'].get(category,0)
        limit=value['limits'].get(category)
        if limit is not None and used+count>limit:
            raise BudgetExhausted(f'研究方案{category}预算已达上限{limit}，已使用{used}；未执行额外操作。')
        value['used'][category]=used+count
        if operation_id is not None:value['operations'][operation_id]=operation
        value['updatedAt']=_stamp()
        db.execute("UPDATE records SET body=? WHERE kind='research_budget' AND id=?",(json.dumps(value,ensure_ascii=False),budget_id))
        return value


from contextvars import ContextVar
_computation_context=ContextVar('research_computation_budget',default=None)


@contextmanager
def computation_budget(db_path,budget_id):
    token=_computation_context.set((db_path,budget_id))
    try:
        for category in ('trainingTasks','backtestTasks','rollingWindows'):reserve(db_path,budget_id,category,0)
        yield
    finally:_computation_context.reset(token)


def observe_computation(category):
    context=_computation_context.get()
    if context is not None:return reserve(*context,category)
