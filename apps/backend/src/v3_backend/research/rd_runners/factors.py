"""Execute native factor workspaces and retain bounded prefix consistency checks."""
import uuid
from pathlib import Path

from . import protocol


def validate(values, daily, require_finite=True):
    import numpy as np
    import pandas as pd
    if isinstance(values, pd.Series):
        values = values.to_frame()
    if not isinstance(values, pd.DataFrame) or values.shape[1] != 1:
        raise ValueError('原生因子须输出单数值列DataFrame')
    if not isinstance(values.index, pd.MultiIndex) or list(values.index.names) != ['datetime', 'instrument']:
        raise ValueError('原生因子索引须为datetime/instrument')
    if values.index.duplicated().any() or not values.index.isin(daily.index).all():
        raise ValueError('原生因子索引重复或包含输入之外的日期/证券')
    values = values.sort_index().apply(pd.to_numeric, errors='raise')
    if np.isinf(values.to_numpy()).any() or (require_finite and not np.isfinite(values.to_numpy()).any()):
        raise ValueError('原生因子无有限输出或包含无穷值')
    return values


def execute_and_check(workspace, output):
    import numpy as np
    import pandas as pd
    from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
    from rdagent.components.coder.factor_coder.factor import FactorFBWorkspace
    config = protocol.config()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    daily = pd.read_hdf(Path(FACTOR_COSTEER_SETTINGS.data_folder) / 'daily_pv.h5')
    execution, generated = workspace.execute(data_type='Full')
    (output / 'execution.txt').write_text(execution, encoding='utf-8')
    values = validate(generated, daily)
    dates = pd.DatetimeIndex(sorted(daily.index.get_level_values(0).unique()))
    if len(dates) < 3:
        raise ValueError('原生因子截断检查至少需要三个交易日')
    # These are explicit sampled checks, not a mathematical all-code causality proof.
    cutoffs = sorted(set([dates[len(dates)//2], dates[-2], pd.Timestamp(config['periods']['trainEnd'])]))
    checks = []
    original = FACTOR_COSTEER_SETTINGS.data_folder
    try:
        for cutoff in cutoffs:
            if cutoff < dates[0] or cutoff >= dates[-1]:
                continue
            folder = output / ('prefix-' + cutoff.strftime('%Y%m%d'))
            folder.mkdir(parents=True, exist_ok=True)
            truncated = daily.loc[daily.index.get_level_values(0) <= cutoff]
            truncated.to_hdf(folder / 'daily_pv.h5', key='data', mode='w')
            FACTOR_COSTEER_SETTINGS.data_folder = str(folder)
            probe = FactorFBWorkspace(target_task=workspace.target_task)
            probe.inject_files(**dict(workspace.file_dict))
            feedback, candidate = probe.execute(data_type='Full')
            (folder / 'execution.txt').write_text(feedback, encoding='utf-8')
            candidate = validate(candidate, truncated, require_finite=False)
            expected = values.loc[values.index.get_level_values(0) <= cutoff]
            if not candidate.index.equals(expected.index) or not np.allclose(
                    candidate.to_numpy(), expected.to_numpy(), rtol=1e-6, atol=1e-8, equal_nan=True):
                protocol.write_json(output / 'prefix_checks.json', {'status': 'failed', 'cutoff': str(cutoff), 'checks': checks})
                raise ValueError('因子截断未来数据后历史输出改变: ' + cutoff.strftime('%Y-%m-%d'))
            checks.append({'cutoff': cutoff.strftime('%Y-%m-%d'), 'rows': len(candidate), 'passed': True})
    finally:
        FACTOR_COSTEER_SETTINGS.data_folder = original
    path = output / 'factor.parquet'
    values.columns = [workspace.target_task.factor_name]
    values.to_parquet(path)
    protocol.write_json(output / 'prefix_checks.json', {'status': 'passed', 'checks': checks,
        'scope': 'sampled data-prefix execution consistency; not universal causality proof'})
    protocol.event('factor_prefix_checked', factorPath=str(path), checks=checks)
    return path
