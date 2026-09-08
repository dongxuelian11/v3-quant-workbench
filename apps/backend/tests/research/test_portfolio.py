import numpy as np
import pandas as pd
import unittest

from v3_backend.research.portfolio import construct_portfolio, _solve_weights, portfolio_turnover


def direct(method, gross=.9, cap=None, mu=None):
    return _solve_weights(method, np.array([.6, .3]), np.diag([.04, .16]),
                          None if mu is None else np.array(mu), np.zeros(2),
                          np.zeros(2), np.full(2, 1. if cap is None else cap), [],
                          {'grossExposure': gross, 'riskAversion': 3, 'turnoverLimit': None})


def test_turnover_includes_cash():
    assert np.isclose(portfolio_turnover(np.array([.5, .45]), np.zeros(2)), .95)
    assert np.isclose(portfolio_turnover(np.array([.4, .4]), np.array([.5, .3])), .1)


def test_equal_score_and_capacity():
    scores = pd.Series({'A': 2., 'B': 1.})
    for method, expected in [('equal', [.45, .45]), ('score', [.6, .3])]:
        result = construct_portfolio(scores, pd.DataFrame(), {'method': method, 'grossExposure': .9})
        assert result['executable'], result['conflicts']
        np.testing.assert_allclose(result['weights'], expected, atol=2e-6)
    result = construct_portfolio(scores, pd.DataFrame(), {'maxWeight': .3})
    assert np.isclose(result['actualExposure'], .6, atol=2e-6)
    assert np.isclose(result['cash'], .4, atol=2e-6)
    result = construct_portfolio(scores, pd.DataFrame(), {'turnoverLimit': .1})
    assert np.isclose(result['actualExposure'], .1, atol=2e-6)


def test_risk_parity_and_constrained_contributions():
    w, _, conflicts = direct('risk_parity')
    assert not conflicts
    np.testing.assert_allclose(w, [.6, .3], atol=2e-5)
    w, _, conflicts = direct('risk_parity', cap=.5)
    assert not conflicts
    np.testing.assert_allclose(w, [.5, .4], atol=2e-5)
    rc = w * (np.diag([.04, .16]) @ w)
    np.testing.assert_allclose(rc / rc.sum(), [.280898876, .719101124], atol=2e-5)


def test_mean_variance_annual_objective():
    w, _, conflicts = direct('mean_variance', gross=1., mu=[.06, .12])
    assert not conflicts
    np.testing.assert_allclose(w, [.75, .25], atol=2e-5)


def test_lock_conflict_preserves_current_and_exit_names():
    current = pd.Series({'A': .6, 'EXIT': .2})
    result = construct_portfolio(pd.Series({'B': 1.}), pd.DataFrame(), {'maxWeight': .3},
                                 current, locked_weights=pd.Series({'A': .6}))
    assert not result['executable']
    assert result['weights']['A'] == .6
    assert result['weights']['EXIT'] == .2
    assert result['lockedWeights']['A'] == .6


def test_exit_and_locked_weights_remain_in_universe():
    result = construct_portfolio(pd.Series({'B': 1.}), pd.DataFrame(), {'grossExposure': .8},
                                 pd.Series({'A': .3, 'EXIT': .2}), locked_weights=pd.Series({'A': .3}))
    assert result['executable'], result['conflicts']
    np.testing.assert_allclose(result['weights'].reindex(['A', 'B', 'EXIT']), [.3, .5, 0], atol=2e-6)


def test_industry_cap_and_missing_coverage():
    scores = pd.Series({'A': 2., 'B': 1.})
    result = construct_portfolio(scores, pd.DataFrame(), {'industryCap': .4}, industries=pd.Series({'A': 'X', 'B': 'X'}))
    assert result['executable']
    assert np.isclose(result['actualExposure'], .4, atol=2e-6)
    result = construct_portfolio(scores, pd.DataFrame(), {'industryCap': .4}, industries=pd.Series({'A': 'X'}))
    assert not result['executable']
    assert any('行业' in value and 'B' in value for value in result['conflicts'])


def history():
    rng = np.random.default_rng(7)
    return pd.DataFrame(rng.normal(.0003, .01, (260, 2)), columns=['A', 'B'], index=pd.bdate_range('2020-01-01', periods=260))


def test_history_filter_and_missing_model_returns():
    data = history()
    data.loc[data.index[20:], 'B'] = np.nan
    result = construct_portfolio(pd.Series({'A': 1., 'B': 2.}), data, {'method': 'risk_parity'})
    assert result['executable'], result['conflicts']
    assert np.isclose(result['weights']['B'], 0, atol=2e-6)
    assert any('B' in value for value in result['warnings'])
    result = construct_portfolio(pd.Series({'A': 1.}), data, {'method': 'mean_variance', 'returnSource': 'model'})
    assert not result['executable']
    assert any('预测' in value for value in result['conflicts'])


def test_joint_missing_and_no_observations_are_not_filled():
    data = history()
    data.iloc[:100, 0] = np.nan
    data.iloc[160:, 1] = np.nan
    result = construct_portfolio(pd.Series({'A': 1., 'B': 2.}), data, {'method': 'risk_parity'})
    assert not result['executable']
    assert any('共同' in value for value in result['conflicts'])
    result = construct_portfolio(pd.Series({'A': 1.}), pd.DataFrame(), {'method': 'risk_parity'})
    assert result['executable']
    assert result['cash'] == 1
    assert any('有效样本不足，保留现金' in value for value in result['warnings'])
    result = construct_portfolio(pd.Series({'A': 1.}), pd.DataFrame(),
                                 {'method': 'risk_parity', 'turnoverLimit': .1}, pd.Series({'EXIT': .8}))
    assert not result['executable']
    assert result['weights']['EXIT'] == .8


def test_lookback_uses_latest_sorted_observations():
    data = history()
    scores = pd.Series({'A': 1., 'B': 2.})
    a = construct_portfolio(scores, data, {'method': 'mean_variance'})
    b = construct_portfolio(scores, data.iloc[-252:].iloc[::-1], {'method': 'mean_variance'})
    assert a['executable'] and b['executable']
    np.testing.assert_allclose(a['weights'], b['weights'], atol=2e-6)


def test_joint_caps_and_turnover_preserve_all_positions():
    result = construct_portfolio(pd.Series({'A': 2., 'B': 1.}), pd.DataFrame(),
                                 {'grossExposure': .9, 'maxWeight': .4, 'industryCap': .5, 'turnoverLimit': .1},
                                 pd.Series({'A': .2, 'B': .2}), pd.Series({'A': 'X', 'B': 'X'}),
                                 pd.Series({'A': .2}))
    assert result['executable'], result['conflicts']
    assert np.isclose(result['actualExposure'], .5, atol=2e-6)
    assert result['weights']['A'] >= .2 - 2e-6
    assert result['weights'].max() <= .4 + 2e-6
    assert result['turnover'] <= .1 + 2e-6
    result = construct_portfolio(pd.Series({'B': 1.}), pd.DataFrame(), {'turnoverLimit': .1},
                                 pd.Series({'EXIT': .8}))
    assert not result['executable']
    assert result['weights']['EXIT'] == .8
    assert result['turnover'] == 0


def test_equal_reports_observed_risk_contributions_and_model_forecasts_work():
    scores = pd.Series({'A': 1., 'B': 2.})
    equal = construct_portfolio(scores, history(), {'method': 'equal'})
    assert equal['executable']
    assert np.isclose(equal['riskContributions'].sum(), 1.)
    model = construct_portfolio(scores, history(), {'method': 'mean_variance', 'returnSource': 'model'},
                                expected_returns=pd.Series({'A': .06, 'B': .12}))
    assert model['executable'], model['conflicts']
    assert np.isfinite(model['riskContributions']).all()


def test_solver_failure_does_not_replace_current_weights():
    from unittest.mock import patch
    import cvxpy as cp
    with patch('v3_backend.research.portfolio.cp.Problem.solve', side_effect=cp.error.SolverError('unavailable')):
        result = construct_portfolio(pd.Series({'A': 1.}), pd.DataFrame(), {}, pd.Series({'A': .2}))
    assert not result['executable']
    assert result['weights']['A'] == .2
    assert any('unavailable' in value for value in result['conflicts'])


def test_infeasible_fallback_marks_uncovered_exit_risk_unavailable():
    data = history().rename(columns={'B': 'EXIT'})
    current = pd.Series({'A': .2, 'EXIT': .8})
    result = construct_portfolio(pd.Series({'A': 1.}), data,
                                 {'method': 'risk_parity', 'turnoverLimit': .1}, current)
    assert not result['executable']
    pd.testing.assert_series_equal(result['weights'], current)
    assert result['riskContributions'].isna().all()
    assert any('覆盖不足' in value and 'EXIT' in value for value in result['warnings'])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items() if name.startswith('test_') and callable(value))

