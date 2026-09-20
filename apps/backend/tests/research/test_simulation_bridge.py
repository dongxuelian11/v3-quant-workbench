import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from qlib.config import C
from v3_backend.research import data, simulation, worker
from v3_backend.research.jobs import validate_spec
from v3_backend.research.server import Service
from v3_backend.research.storage import read_json, write_json


class SimulationBridgeTest(unittest.TestCase):
    def test_queued_account_uses_frozen_strategy_and_exports_net_returns(self):
        C.set(region='cn')
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / 'app')
            try:
                project = service.store.create_project(Path(directory) / 'project', '模拟研究')
                project['universe'].update(symbols=['SH600000'], minListingDays=0, excludeST=False)
                project['settings']['backtest'] = dict(template='multi_factor', factorIds=[], rebalance='daily',
                    costs={'slippage': 0}, dailyCode="def decide(context):\n return {'targets': {'SH600000': .5}}")
                project = service.store.save_project(project)
                # A complete rule strategy does not require an unrelated factor.
                validate_spec(dict(projectId=project['id'], kind='backtest.run', parameters=project['settings']['backtest']))
                account = service.request('simulation.accounts.create', dict(projectId=project['id'], strategyId='default',
                    name='模拟', startDate='2025-01-02', capital=10000))
                with patch.object(service.jobs, '_start_next'):
                    job = service.jobs.submit(dict(projectId=project['id'], kind='simulation.advance',
                        parameters={'accountId': account['id'], 'endDate': '2025-01-03'}))
                service.request('strategies.save', dict(projectId=project['id'], strategy={'id': 'default'},
                    settingsPatch={'backtest': {'dailyCode': "def decide(context):\n return {'targets': {}}"}}))
                frame = pd.DataFrame([dict(date=pd.Timestamp(date), symbol='SH600000', rawOpen=10., rawClose=10.,
                    rawPreclose=10., open=10., high=10., low=10., close=10., factor=1., volume=100000,
                    tradestatus='1', isST='0') for date in ['2025-01-02', '2025-01-03']])
                folder = Path(data.project_data(project)['path']) / 'data'
                folder.mkdir(parents=True, exist_ok=True)
                frame.to_parquet(folder / 'prices.parquet', index=False)
                run_folder = Path(project['path']) / '.research' / 'runs' / job['id']
                write_json(run_folder / 'request.json', {'appData': str(service.store.root), 'job': job})
                with patch.object(simulation.engines, 'prepare', return_value=frame):
                    self.assertEqual(worker.run(run_folder), 0, read_json(run_folder / 'result.json'))
                experiment = read_json(run_folder / 'result.json')['experiment']
                service.store.save_experiment(project['id'], experiment)
                saved = service.request('simulation.accounts.get', {'projectId': project['id'], 'accountId': account['id']})
                self.assertEqual(saved['state']['holdings']['SH600000']['quantity'], 500)
                self.assertEqual(saved['asOfDate'], '2025-01-03')
                result = service.experiment_details(project['id'], job['id'])
                self.assertAlmostEqual(result['series'][0]['points'][-1]['value'], saved['nav'] / 10000)
                self.assertTrue(all(not Path(a['path']).is_absolute() for a in experiment['artifacts']))
                service.jobs.cancel(job['id'])
                service.request('simulation.accounts.save', {'projectId': project['id'], 'accountId': account['id'], 'paused': True})
                with self.assertRaisesRegex(ValueError, '已暂停'):
                    service.jobs.submit(dict(projectId=project['id'], kind='simulation.advance', parameters={'accountId': account['id']}))
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
