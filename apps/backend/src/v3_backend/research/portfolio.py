"""Long-only research portfolios using observed returns and explicit cash constraints.

The caller supplies returns known at the decision timestamp (never future labels).
This module does not fetch data, mutate positions, or round executable share orders.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import cvxpy as cp
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf


DEFAULTS = dict(method='equal', grossExposure=.95, maxWeight=None, industryCap=None,
                turnoverLimit=None, lookback=252, minObservations=126,
                riskAversion=3., returnSource='historical')
TOL = 2e-6


def portfolio_turnover(weights: np.ndarray, current: np.ndarray) -> float:
    """Half L1 over stocks AND cash; opening a 95% position costs 95%."""
    return float((np.abs(weights - current).sum() + abs(weights.sum() - current.sum())) / 2)


def _violations(weights, current, lower, upper, groups, config, exposure=None):
    errors = []
    if not np.isfinite(weights).all():
        return ['求解结果包含非有限权重']
    if np.any(weights < lower - TOL):
        errors.append('不可卖持仓下限未满足')
    if np.any(weights > upper + TOL):
        errors.append('单股上限或退出股票约束未满足')
    if weights.sum() > config['grossExposure'] + TOL:
        errors.append('总仓位上限未满足')
    if exposure is not None and abs(weights.sum() - exposure) > TOL:
        errors.append('固定投资总额未满足')
    if any(weights[index].sum() > cap + TOL for index, cap in groups):
        errors.append('行业上限未满足')
    limit = config.get('turnoverLimit')
    if limit is not None and portfolio_turnover(weights, current) > limit + TOL:
        errors.append('含现金换手上限未满足')
    return errors


def _solve_weights(method, initial, covariance, expected, current, lower, upper, groups, config):
    """Thin numeric seam, accepting annual covariance directly for hand checks.

    Returns (weights or None, JSON diagnostics, conflicts). Constraints are applied
    during every optimization; no post-hoc clipping/renormalization of a portfolio.
    """
    n = len(current)
    if not n:
        return np.empty(0), {'feasibleExposure': 0.}, []
    if np.any(lower > upper + TOL):
        return None, {}, ['不可卖持仓下限高于单股上限或可持仓范围']
    w = cp.Variable(n)
    constraints = [w >= lower, w <= upper, cp.sum(w) <= config['grossExposure']]
    for index, cap in groups:
        constraints.append(cp.sum(w[index]) <= cap)
    limit = config.get('turnoverLimit')
    if limit is not None:
        constraints.append((cp.norm1(w - current) + cp.abs(cp.sum(w) - current.sum())) / 2 <= limit)

    def solve(objective, extra=()):
        problem = cp.Problem(objective, constraints + list(extra))
        problem.solve(solver='CLARABEL', tol_gap_abs=1e-9, tol_feas=1e-9, tol_gap_rel=1e-9)
        if problem.status != cp.OPTIMAL or w.value is None:
            return None, problem.status
        return np.asarray(w.value, dtype=float).reshape(n), problem.status

    try:
        capacity, status = solve(cp.Maximize(cp.sum(w)))
        if capacity is None:
            return None, {'capacityStatus': status}, ['共同约束不可行：请检查不可卖持仓、退出股票、仓位和换手上限']
        exposure = min(float(capacity.sum()), float(config['grossExposure']))
        if exposure < TOL:
            exposure = 0.
        diagnostic = {'feasibleExposure': exposure, 'capacityStatus': status}
        fixed = [cp.sum(w) == exposure]
        if exposure == 0:
            zeros = np.zeros(n)
            return zeros, diagnostic, _violations(zeros, current, lower, upper, groups, config, exposure)
        if method == 'mean_variance':
            if covariance is None or expected is None:
                return None, diagnostic, ['均值方差缺少收益预测或协方差']
            objective = cp.Minimize(config['riskAversion'] * cp.quad_form(w, cp.psd_wrap(covariance)) - expected @ w)
        else:
            if method == 'risk_parity':
                if covariance is None:
                    return None, diagnostic, ['风险平价缺少协方差']
                variance = np.diag(covariance)
                active = upper > TOL
                if np.any(variance[active] <= 0):
                    return None, diagnostic, ['风险平价存在零方差股票，无法定义风险贡献']
                initial = np.where(active, 1 / np.sqrt(np.maximum(variance, 1e-30)), 0.)
            desired = initial / initial.sum() * exposure if initial.sum() > 0 else np.zeros(n)
            objective = cp.Minimize(cp.sum_squares(w - desired))
        solution, status = solve(objective, fixed)
        diagnostic['solverStatus'] = status
        if solution is None:
            return None, diagnostic, ['目标组合求解失败：' + status]
        if method == 'risk_parity':
            active = upper > TOL
            count = int(active.sum())

            def objective_rp(x):
                contributions = x * (covariance @ x)
                variance = contributions.sum()
                if variance <= 1e-30:
                    return 1e10
                return float(np.square(contributions[active] / variance - 1 / count).sum())

            cons = [{'type': 'eq', 'fun': lambda x: x.sum() - exposure}]
            cons.extend({'type': 'ineq', 'fun': lambda x, idx=idx, cap=cap: cap - x[idx].sum()}
                        for idx, cap in groups)
            if limit is not None:
                cons.append({'type': 'ineq', 'fun': lambda x: limit - portfolio_turnover(x, current)})
            result = minimize(objective_rp, solution, method='SLSQP', bounds=list(zip(lower, upper)),
                              constraints=cons, options={'ftol': 1e-12, 'maxiter': 1000})
            diagnostic.update(solverStatus=str(result.message), riskContributionSquaredError=float(result.fun))
            if not result.success:
                return None, diagnostic, ['风险平价求解失败：' + str(result.message)]
            solution = result.x
        # Remove only solver roundoff at exact zero, never repair an infeasible result.
        solution[np.abs(solution) < 1e-9] = 0.
        return solution, diagnostic, _violations(solution, current, lower, upper, groups, config, exposure)
    except (cp.error.SolverError, ValueError, np.linalg.LinAlgError) as exc:
        return None, {}, ['组合求解失败：' + str(exc)]


def construct_portfolio(scores: pd.Series, returns: pd.DataFrame, config: dict,
                        current_weights: pd.Series | None = None,
                        industries: pd.Series | None = None,
                        locked_weights: pd.Series | None = None,
                        expected_returns: pd.Series | None = None) -> dict:
    """Construct a portfolio; an infeasible result always preserves current weights.

    ``returns`` contains daily simple returns known by T, not prices or labels;
    ``expected_returns`` contains genuine ANNUAL model forecasts. Each column and
    series index names a security. Historical mean/covariance use the latest sorted
    lookback rows with complete common observations, without imputing missing data.
    """
    settings = {**DEFAULTS, **config}
    warnings, conflicts = [], []
    scores = scores.copy()
    current_weights = pd.Series(dtype=float) if current_weights is None else current_weights.copy()
    locked_weights = pd.Series(dtype=float) if locked_weights is None else locked_weights.copy()
    # Never drop positions just because they no longer appear among selected scores.
    universe = scores.index.union(current_weights.index, sort=False).union(locked_weights.index, sort=False)
    if any(not series.index.is_unique for series in (scores, current_weights, locked_weights)):
        raise ValueError('评分、当前持仓和不可卖持仓的证券代码必须唯一')
    current = pd.to_numeric(current_weights.reindex(universe, fill_value=0), errors='coerce').to_numpy(dtype=float)
    lower = pd.to_numeric(locked_weights.reindex(universe, fill_value=0), errors='coerce').to_numpy(dtype=float)
    covariance = None
    risk_index = pd.Index([])
    observations = 0
    diagnostic = {}

    def finish(weights, executable):
        rc = pd.Series(np.nan, index=universe, dtype=float)
        uncovered = universe[(weights != 0) & ~universe.isin(risk_index)]
        if len(uncovered):
            warnings.append('持仓风险覆盖不足，风险贡献不可用：' + '、'.join(map(str, uncovered)))
        elif covariance is not None:
            contributions = weights * (covariance @ weights)
            if contributions.sum() > 1e-30:
                rc = pd.Series(contributions / contributions.sum(), index=universe)
        return dict(weights=pd.Series(weights, index=universe), cash=float(1 - weights.sum()),
                    targetExposure=settings['grossExposure'], actualExposure=float(weights.sum()),
                    turnover=portfolio_turnover(weights, current), riskContributions=rc,
                    executable=executable, conflicts=conflicts, warnings=warnings,
                    lockedWeights=pd.Series(lower, index=universe),
                    diagnostics={**diagnostic, 'observations': observations, 'covarianceAnnualization': 252,
                                 'riskSymbols': risk_index.tolist()})

    for key in ('grossExposure', 'maxWeight', 'industryCap', 'turnoverLimit'):
        value = settings[key]
        if value is None and key != 'grossExposure':
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 1:
            conflicts.append(f'{key}必须为0至1的比例' + ('或null' if key != 'grossExposure' else ''))
    if settings['method'] not in ('equal', 'score', 'risk_parity', 'mean_variance'):
        conflicts.append('未知组合方法')
    for key in ('lookback', 'minObservations'):
        if isinstance(settings[key], bool) or not isinstance(settings[key], int) or settings[key] < 2:
            conflicts.append(f'{key}必须为至少2的整数')
    if not isinstance(settings['riskAversion'], (float, int)) or not np.isfinite(settings['riskAversion']) or settings['riskAversion'] < 0:
        conflicts.append('风险厌恶系数必须为非负有限数')
    if settings['returnSource'] not in ('historical', 'model'):
        conflicts.append('收益来源必须为historical或model')
    if not np.isfinite(current).all() or (current < 0).any() or current.sum() > 1 + TOL:
        conflicts.append('当前持仓权重必须非负、有限且总额不超过1')
    if not np.isfinite(lower).all() or (lower < 0).any() or np.any(lower > current + TOL):
        conflicts.append('不可卖持仓必须非负、有限且不大于当前持仓')
    if conflicts:
        return finish(current, False)

    values = pd.to_numeric(scores.reindex(universe), errors='coerce').replace([np.inf, -np.inf], np.nan)
    eligible = values.notna().to_numpy()
    missing_scores = scores.index.difference(values.dropna().index).tolist()
    if missing_scores:
        warnings.append('评分缺失，排除候选：' + '、'.join(map(str, missing_scores)))
    method = settings['method']
    needs_risk = method in ('risk_parity', 'mean_variance')
    mu = None
    if needs_risk:
        if not returns.columns.is_unique or not returns.index.is_unique:
            conflicts.append('历史收益日期及证券列必须唯一')
            return finish(current, False)
        sample = returns.sort_index().tail(settings['lookback']).reindex(columns=universe)
        sample = sample.apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan)
        adequate = (sample.notna().sum() >= settings['minObservations']).to_numpy()
        removed = universe[eligible & ~adequate]
        if len(removed):
            warnings.append('历史有效观测不足，排除候选：' + '、'.join(map(str, removed)))
        eligible &= adequate
        if np.any((lower > 0) & ~adequate):
            conflicts.append('不可卖持仓历史观测不足，无法估计组合风险：' + '、'.join(map(str, universe[(lower > 0) & ~adequate])))
        risk_mask = eligible | (lower > 0)
        risk_index = universe[risk_mask]
        if not len(risk_index):
            warnings.append('有效样本不足，保留现金')
            zeros = np.zeros(len(universe))
            weights, diagnostic, errors = _solve_weights(method, zeros, None, None, current, lower,
                                                          zeros, [], settings)
            conflicts.extend(errors)
            return finish(current if weights is None or conflicts else weights, not conflicts and weights is not None)
        common = sample.loc[:, risk_index].dropna()
        observations = len(common)
        if len(risk_index) and observations < settings['minObservations']:
            conflicts.append(f'共同有效观测仅{observations}日，至少需要{settings["minObservations"]}日；未填补缺失收益')
        if conflicts:
            return finish(current, False)
        estimator = LedoitWolf().fit(common.to_numpy())
        covariance = np.zeros((len(universe), len(universe)))
        positions = np.flatnonzero(risk_mask)
        covariance[np.ix_(positions, positions)] = estimator.covariance_ * 252
        if method == 'mean_variance':
            if settings['returnSource'] == 'model':
                if expected_returns is None or not expected_returns.index.is_unique:
                    conflicts.append('均值方差需要真实年化模型收益预测，不能使用排名或评分代替')
                else:
                    forecasts = pd.to_numeric(expected_returns.reindex(risk_index), errors='coerce')
                    if not np.isfinite(forecasts.to_numpy()).all():
                        conflicts.append('真实年化收益预测覆盖缺失：' + '、'.join(map(str, risk_index[~np.isfinite(forecasts.to_numpy())])))
                    else:
                        mu = np.zeros(len(universe))
                        mu[positions] = forecasts.to_numpy()
            else:
                mu = np.zeros(len(universe))
                mu[positions] = common.mean().to_numpy() * 252
    upper = np.where(eligible, 1. if settings['maxWeight'] is None else settings['maxWeight'], lower)
    if settings['maxWeight'] is not None:
        upper = np.minimum(upper, settings['maxWeight'])
    groups = []
    if settings['industryCap'] is not None:
        if industries is not None and not industries.index.is_unique:
            conflicts.append('行业数据证券代码必须唯一')
        else:
            industry = pd.Series(index=universe, dtype=object) if industries is None else industries.reindex(universe)
            missing = industry.isna() | industry.astype(str).str.strip().str.lower().isin(['', 'unknown', '未知', '未分类', 'none', 'nan'])
            if (missing.to_numpy() & (upper > 0)).any():
                conflicts.append('行业上限已启用但行业覆盖缺失：' + '、'.join(map(str, universe[missing.to_numpy() & (upper > 0)])))
            for group in industry[~missing].unique():
                groups.append((np.flatnonzero((industry == group).to_numpy()), settings['industryCap']))
    if conflicts:
        return finish(current, False)
    # Descending score gets the largest positive rank. Negative raw scores remain
    # valid; no negative allocation or zero-sum division is invented.
    initial = np.zeros(len(universe))
    if method == 'score':
        initial[eligible] = values.iloc[np.flatnonzero(eligible)].rank(method='average', ascending=True).to_numpy()
    else:
        initial[eligible] = 1.
    weights, diagnostic, errors = _solve_weights(method, initial, covariance, mu, current, lower, upper, groups, settings)
    conflicts.extend(errors)
    if weights is None or conflicts:
        return finish(current, False)
    if weights.sum() < settings['grossExposure'] - TOL:
        warnings.append(f'共同约束下最多投资{weights.sum():.2%}，低于请求仓位{settings["grossExposure"]:.2%}；剩余保留现金')
    if method == 'risk_parity' and diagnostic.get('riskContributionSquaredError', 0) > 1e-8:
        warnings.append('约束下风险贡献未完全相等，已返回实际风险贡献；未放宽上限')
    if not needs_risk and weights.sum() > TOL:
        # Equal/rank construction does not require a risk estimate. Report real
        # contributions when there is sufficient coverage, otherwise mark them
        # unavailable rather than using invented zero returns/covariances.
        risk_index = universe[weights > TOL]
        if returns.columns.is_unique and returns.index.is_unique:
            sample = returns.sort_index().tail(settings['lookback']).reindex(columns=risk_index)
            sample = sample.apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
            observations = len(sample)
            if observations >= settings['minObservations']:
                covariance = np.zeros((len(universe), len(universe)))
                positions = np.flatnonzero(weights > TOL)
                covariance[np.ix_(positions, positions)] = LedoitWolf().fit(sample.to_numpy()).covariance_ * 252
        if covariance is None:
            warnings.append('共同历史收益观测不足或重复，风险贡献不可用；等权/评分组合仍按约束构建')
    return finish(weights, True)
