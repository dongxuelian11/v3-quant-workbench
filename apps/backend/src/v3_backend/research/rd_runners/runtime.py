"""Adapt native RD-Agent execution to the already installed Linux virtualenv."""
import importlib
import os
import sys
from pathlib import Path

from . import protocol


def local_env(conf_type=None, extra_volumes=None, running_timeout_period=600, enable_cache=None, conf=None):
    from rdagent.utils.env import LocalConf, LocalEnv
    return LocalEnv(LocalConf(default_entry='python', bin_path=str(Path(sys.executable).parent),
        extra_volumes=dict(extra_volumes or {}), running_timeout_period=running_timeout_period,
        enable_cache=False, live_output=False))


def local_conf(**kwargs):
    from rdagent.utils.env import LocalConf
    return LocalConf(default_entry='python', bin_path=str(Path(sys.executable).parent), enable_cache=False, live_output=False)


def configure(work):
    from rdagent.core.conf import RD_AGENT_SETTINGS
    from rdagent.oai.llm_conf import LLM_SETTINGS
    from rdagent.log.conf import LOG_SETTINGS
    from rdagent.log import rdagent_logger as logger
    from rdagent.components.coder.CoSTEER.config import CoSTEER_SETTINGS
    from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
    from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
    config = protocol.config()
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')
    RD_AGENT_SETTINGS.workspace_path = work / 'workspaces'
    RD_AGENT_SETTINGS.cache_with_pickle = False
    RD_AGENT_SETTINGS.multi_proc_n = 1
    RD_AGENT_SETTINGS.step_semaphore = 1
    RD_AGENT_SETTINGS.subproc_step = False
    # Real artifacts stay in their workspaces; checkpoint code only, not linked data.
    RD_AGENT_SETTINGS.workspace_ckp_white_list_names = ['factor.py', 'model.py']
    LLM_SETTINGS.backend = 'v3_backend.research.rd_runners.service.V3APIBackend'
    LLM_SETTINGS.log_llm_chat_content = False
    LLM_SETTINGS.max_retry = 1
    LLM_SETTINGS.retry_wait_seconds = 1
    LLM_SETTINGS.prompt_cache_path = str(work / 'native-session-chat.sqlite')
    for setting in (CoSTEER_SETTINGS, FACTOR_COSTEER_SETTINGS, MODEL_COSTEER_SETTINGS):
        setting.max_loop = 1
        setting.fail_task_trial_limit = 1
        setting.coder_use_cache = False
    FACTOR_COSTEER_SETTINGS.python_bin = sys.executable
    FACTOR_COSTEER_SETTINGS.data_folder = str(work / 'factor-data')
    FACTOR_COSTEER_SETTINGS.data_folder_debug = str(work / 'factor-data')
    FACTOR_COSTEER_SETTINGS.file_based_execution_timeout = int(config.get('factorTimeoutSeconds', 600))
    MODEL_COSTEER_SETTINGS.env_type = 'conda'  # Native branch name; factory below uses LocalConf.
    # Imported aliases need explicit rebinding, including ModelFBWorkspace's direct factory.
    for name in ('rdagent.components.coder.factor_coder.config',
                 'rdagent.components.coder.model_coder.conf',
                 'rdagent.scenarios.qlib.experiment.quant_experiment'):
        module = importlib.import_module(name)
        for attr in ('get_factor_env', 'get_model_env'):
            if hasattr(module, attr):
                setattr(module, attr, local_env)
    model_module = importlib.import_module('rdagent.components.coder.model_coder.model')
    model_module.QlibCondaEnv = local_env
    model_module.QlibCondaConf = local_conf
    LOG_SETTINGS.trace_path = str(work / 'native-log')
    logger.set_storages_path(Path(LOG_SETTINGS.trace_path))
    # Upstream emits debug_llm objects even with log_llm_chat_content=False.
    original = logger.log_object

    def log_object(obj, *, tag=''):
        if 'debug_llm' in tag:
            return
        original(obj, tag=tag)
        if tag == 'evolving code':
            protocol.event('code_attempt_completed', workspacePaths=[str(item.workspace_path) for item in obj if item is not None])

    logger.log_object = log_object


def prepare_data(work):
    import pandas as pd
    import numpy as np
    config = protocol.config()
    data = pd.read_parquet(config['datasetPath'])
    if not data.partition.isin(['train', 'valid']).all():
        raise ValueError('研发输入只能含训练和验证分区，测试数据不得进入原生循环')
    source = Path(config['factorDataPath'])
    daily = pd.read_parquet(source) if source.suffix == '.parquet' else pd.read_hdf(source)
    if not isinstance(daily.index, pd.MultiIndex) and {'datetime', 'instrument'}.issubset(daily):
        daily = daily.set_index(['datetime', 'instrument'])
    if not isinstance(daily.index, pd.MultiIndex) or list(daily.index.names) != ['datetime', 'instrument']:
        raise ValueError('因子行情索引必须为datetime/instrument')
    if not {'$open', '$high', '$low', '$close', '$volume', '$factor'}.issubset(daily):
        raise ValueError('因子行情缺少原生接口所需字段')
    if daily.index.duplicated().any() or daily.empty:
        raise ValueError('因子行情为空或索引重复')
    end = pd.Timestamp(config['periods']['validEnd'])
    if daily.index.get_level_values(0).max() > end:
        raise ValueError('原生因子输入包含验证期之后的行情')
    if not np.isfinite(daily['$factor']).all():
        raise ValueError('因子复权因子包含非有限值')
    folder = work / 'factor-data'
    folder.mkdir(parents=True, exist_ok=True)
    daily.sort_index().to_hdf(folder / 'daily_pv.h5', key='data', mode='w')
    (folder / 'README.md').write_text(
        'Read daily_pv.h5 with pandas.read_hdf. MultiIndex datetime/instrument; columns '
        + ', '.join(daily.columns) + '. Only training and validation dates. '
        'Use current/past rows only; no negative shift, centered windows, full-period fit/normalization. '
        'Write exactly one numeric factor column to result.h5. Missing warmup values stay NaN.', encoding='utf-8')
    return daily
