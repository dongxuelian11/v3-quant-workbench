"""Dated screener conditions over existing research values, with explicit unknowns."""
import math
import numpy as np
import pandas as pd


OPERATORS = {'gt','gte','lt','lte','eq','ne','between','rank_top','rank_bottom','cross_up','cross_down','contains','in'}


def validate(group, ranking_allowed=True, depth=0):
    if not isinstance(group, dict) or depth > 8:
        raise ValueError('条件组格式无效或嵌套过深')
    if 'children' in group:
        if group.get('match') not in {'all','any'} or not isinstance(group['children'], list):
            raise ValueError('条件组请选择全部或任一')
        for child in group['children']:
            validate(child, ranking_allowed, depth+1)
        return
    op = group.get('operator')
    if not group.get('field') or op not in OPERATORS:
        raise ValueError('请选择有效字段和条件运算')
    if op.startswith('rank_') and not ranking_allowed:
        raise ValueError('排名参照的前置条件不能包含排名，避免循环定义')
    if group.get('compareField') and op in {'between','rank_top','rank_bottom','contains','in'}:
        raise ValueError('该条件需要固定值，不支持与字段比较')
    window = group.get('window', 1)
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 252:
        raise ValueError('条件窗口须为1至252个交易日')
    if group.get('occurrence', 'current') not in {'current','all','any'}:
        raise ValueError('未知时序条件')
    if op == 'in':
        if not isinstance(group.get('value'), list): raise ValueError('范围条件需要一个值列表')
    elif not group.get('compareField') and op not in {'contains','eq','ne'}:
        for key in ('value','upper') if op == 'between' else ('value',):
            value = group.get(key)
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
                raise ValueError('条件数值必须为有限数字')
        if op == 'between' and group['value'] > group['upper']:
            raise ValueError('区间下限不能大于上限')
        if op.startswith('rank_') and (group['value'] < 1 or int(group['value']) != group['value']):
            raise ValueError('排名数量须为正整数')


def evaluate(panel, group, reference=None):
    """Panel must include missing sessions on a date/symbol index before temporal rules."""
    validate(group)
    reference = pd.Series(True, index=panel.index) if reference is None else reference.reindex(panel.index).fillna(False)
    details = {}
    def walk(rule):
        if 'children' in rule:
            result = pd.Series(rule['match']=='all', index=panel.index, dtype='boolean')
            for child in rule['children']:
                result = result & walk(child) if rule['match']=='all' else result | walk(child)
            # An empty group means no additional conditions, including a fresh ANY group.
            return result if rule['children'] else pd.Series(True, index=panel.index, dtype='boolean')
        key, op = rule['field'], rule['operator']
        values = panel[key] if key in panel else pd.Series(np.nan, index=panel.index)
        rhs = panel.get(rule['compareField'], pd.Series(np.nan,index=panel.index)) if rule.get('compareField') else rule.get('value')
        known = values.notna()
        ranks = None
        if op in {'contains','in'}:
            mask = values.astype('string').str.contains(str(rhs),regex=False,case=False) if op=='contains' else values.isin(rhs)
        elif op in {'eq','ne'} and not isinstance(rhs,(int,float,pd.Series)):
            mask = values.eq(rhs) if op=='eq' else values.ne(rhs)
        else:
            values = pd.to_numeric(values, errors='coerce').replace([np.inf,-np.inf],np.nan)
            known = values.notna()
            if isinstance(rhs,pd.Series):
                rhs = pd.to_numeric(rhs,errors='coerce').replace([np.inf,-np.inf],np.nan)
                known &= rhs.notna()
            if op.startswith('rank_'):
                eligible = values.where(reference)
                ranks = eligible.groupby(level='date').rank(ascending=op=='rank_bottom',method='min')
                valid = eligible.groupby(level='date').transform('count') >= 2
                known &= ranks.notna() & valid
                mask = ranks.le(float(rhs))
            elif op == 'between':
                mask = values.between(float(rhs),float(rule['upper']))
            elif op.startswith('cross_'):
                delta = values-rhs
                previous = delta.groupby(level='symbol').shift(1)
                known &= previous.notna()
                mask = (delta.gt(0)&previous.le(0)) if op=='cross_up' else (delta.lt(0)&previous.ge(0))
            else:
                mask = getattr(values,{'gt':'gt','gte':'ge','lt':'lt','lte':'le','eq':'eq','ne':'ne'}[op])(rhs)
        result = mask.astype('boolean').where(known,pd.NA)
        occurrence, window = rule.get('occurrence','current'), rule.get('window',1)
        if occurrence != 'current' and window > 1:
            # An unknown observation never silently becomes a false/zero observation.
            valid = result.notna().groupby(level='symbol').transform(lambda x:x.rolling(window,min_periods=window).sum())
            true = result.astype('Float64').groupby(level='symbol').transform(lambda x:x.rolling(window,min_periods=1).sum())
            answer = true.eq(window) if occurrence=='all' else true.gt(0)
            decisive = (valid-true).gt(0) if occurrence=='all' else true.gt(0)
            sessions = pd.Series(1.,index=panel.index).groupby(level='symbol').transform(lambda x:x.rolling(window,min_periods=window).sum())
            result = answer.astype('boolean').where(sessions.eq(window)&(valid.eq(window)|decisive),pd.NA)
        details[rule['id']] = {'field':key,'values':values,'ranks':ranks,'matches':result}
        return result
    return walk(group), details


def weighted_scores(panel, factors, reference):
    if not factors or sum(float(item['weight']) for item in factors) <= 0:
        raise ValueError('请选择因子，权重合计须大于零')
    scores = pd.DataFrame(index=panel.index)
    total = sum(float(item['weight']) for item in factors)
    for item in factors:
        direction, weight = item['direction'], float(item['weight'])
        if direction not in {-1,1} or weight < 0 or not math.isfinite(weight):
            raise ValueError('因子方向应为正向或反向，权重须为有限非负数')
        if not weight: continue
        raw = pd.to_numeric(panel.get(item['id'],pd.Series(np.nan,index=panel.index)),errors='coerce')
        values = (raw*direction).replace([np.inf,-np.inf],np.nan).where(reference)
        groups = values.groupby(level='date')
        ranks = groups.rank(pct=True,method='average').where(groups.transform('nunique').gt(1))
        scores[item['id']] = ranks * (weight/total)
    return scores.sum(axis=1,min_count=len(scores.columns)), scores
