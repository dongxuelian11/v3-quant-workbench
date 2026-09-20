import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research import engines
from test_engines import sample_project


class JobFlowTest(unittest.TestCase):
    def test_worker_analysis_persists_and_exports_full_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, dates, store = sample_project(root)
            service = Service(root / 'app')
            try:
                job = service.jobs.submit(dict(projectId=project['id'], kind='factor.analyze', parameters={'factorIds': ['momentum20'], 'periods': [1, 5], 'quantiles': 5}))
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    job = store.get('job', job['id'])
                    if job['status'] in {'completed', 'failed'}:
                        break
                    time.sleep(.05)
                self.assertEqual(job['status'], 'completed', job['message'])
                result = service.experiment_details(project['id'], job['experimentId'])
                self.assertLessEqual(sum(len(table['rows']) for table in result['tables']), 500)
                exported = service.export(dict(projectId=project['id'], experimentId=job['experimentId'], format='csv', table='momentum20_samples'))
                self.assertGreater(len(pd.read_csv(exported['path'])), 500)
                self.assertTrue(all(not Path(a['path']).is_absolute() for a in result['experiment']['artifacts']))
                service.close()
                moved = root / 'moved-project'
                Path(project['path']).rename(moved)
                reopened = Service(root / 'second-app')
                reopened.request('projects.open', {'path': str(moved)})
                self.assertEqual(len(reopened.request('experiments.list', {'projectId': project['id']})), 1)
                reopened.experiment_details(project['id'], job['experimentId'])
                page = reopened.request('experiments.table', dict(projectId=project['id'], experimentId=job['experimentId'], table='momentum20_samples', symbol='SH600000', offset=2, limit=3))
                self.assertEqual(len(page['rows']), 3)
                self.assertGreater(page['total'], 3)
                self.assertEqual(page['rows'][0]['asset'], 'SH600000')
                self.assertTrue(Path(reopened.export(dict(projectId=project['id'], experimentId=job['experimentId'], format='xlsx'))['path']).exists())
                reopened.close()
            finally:
                service.close()

    def test_lightgbm_and_structured_ai_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, dates, store = sample_project(root)
            output = root / 'lightgbm'
            output.mkdir()
            params = dict(model='lightgbm', factorIds=['momentum20'], trainStart=str(dates[0]), trainEnd=str(dates[59]), validStart=str(dates[60]), validEnd=str(dates[89]), testStart=str(dates[90]), testEnd=str(dates[-1]), labelHorizon=3, hyperparameters={'n_estimators': 3, 'num_leaves': 3})
            result = engines.train(project, params, output, lambda *_: None)
            self.assertIn('test:mse', result['metrics'])
            from pydantic_ai.models.test import TestModel
            from v3_backend.research.ai import chat
            service = Service(root / 'app')
            service.store.settings({'ai': {'baseUrl': 'http://127.0.0.1:1/v1', 'model': 'test', 'apiKey': '', 'temperature': .2}})
            proposal = dict(title='因子分析', description='当前阶段', spec=dict(projectId=project['id'], kind='factor.analyze', parameters={'factorIds': ['momentum20']}, name='测试'))
            model = TestModel(custom_output_args={'message': '测试建议', 'phase': '分析', 'proposals': [proposal], 'experimentIds': []})
            with patch('pydantic_ai.models.openai.OpenAIChatModel', return_value=model):
                answer = chat(service, dict(projectId=project['id'], mode='research', message='分析', history=[]))
            self.assertEqual(answer['proposals'][0]['spec']['kind'], 'factor.analyze')
            self.assertEqual(store.experiments(project['id']), [])  # Advice never silently runs jobs.
            service.close()


if __name__ == '__main__':
    unittest.main()
