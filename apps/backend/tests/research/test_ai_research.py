"""Focused tool and project persistence checks; these do not certify a live provider."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from v3_backend.research import ai
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json


class ResearchAiTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = Service(self.root / 'app')
        self.project = self.service.store.create_project(self.root / 'project', '研究测试')
        self.project_id = self.project['id']
        self.service.store.settings({'ai': {'baseUrl': 'http://127.0.0.1:1/v1', 'model': 'offline-test', 'apiKey': ''}})

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def test_tools_read_actual_table_and_stage_without_starting_jobs(self):
        directory = Path(self.project['path']) / '.research' / 'runs' / 'experiment-1'
        directory.mkdir(parents=True)
        file = directory / 'target_weights.parquet'
        pd.DataFrame([{'symbol': 'SH600000', 'targetWeight': .3}, {'symbol': 'SZ000001', 'targetWeight': .6}]).to_parquet(file)
        self.service.store.save_experiment(self.project_id, dict(
            id='experiment-1', projectId=self.project_id, name='真实文件', kind='backtest.run',
            createdAt='2026-09-08', parameters={'portfolio': {'grossExposure': .9}},
            metrics={'turnover': .9}, artifacts=[{'name': 'target_weights', 'path': str(file), 'type': 'parquet'}],
            summary='现金10%', starred=False))
        write_json(directory / 'details.json', {'executable': True})
        self.service.store.put('job', dict(id='job-1', projectId=self.project_id, status='completed', experimentId='experiment-1'), self.project_id)
        ai.save_state(self.service, {'projectId': self.project_id, 'state': {'phase': '构建组合', 'stageJobIds': ['job-1']}})
        step = 0
        observed = []

        def respond(messages, info):
            nonlocal step
            observed.extend(part for part in messages[-1].parts if isinstance(part, ToolReturnPart))
            calls = [
                ('read_experiment', {'experiment_id': 'experiment-1'}),
                ('read_result_table', {'experiment_id': 'experiment-1', 'table': 'target_weights', 'offset': 1, 'limit': 1}),
                ('get_current_stage', {}),
            ]
            if step < len(calls):
                name, args = calls[step]
                step += 1
                return ModelResponse(parts=[ToolCallPart(name, args)])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                'message': '该实验目标仓位90%，SZ000001目标权重60%。阶段已完成，请讨论下一步。',
                'phase': '讨论组合', 'proposals': [], 'experimentIds': ['experiment-1'],
            })])

        with patch('pydantic_ai.models.openai.OpenAIChatModel', return_value=FunctionModel(respond)), patch.object(self.service.jobs, 'submit') as submit:
            answer = ai.chat(self.service, dict(projectId=self.project_id, mode='research', message='解释阶段结果'))
        submit.assert_not_called()
        self.assertEqual(answer['experimentIds'], ['experiment-1'])
        returned = {part.tool_name: part.content for part in observed}
        self.assertEqual(returned['read_experiment']['experiment']['metrics']['turnover'], .9)
        self.assertEqual(returned['read_result_table']['rows'], [{'symbol': 'SZ000001', 'targetWeight': .6}])
        self.assertEqual(returned['get_current_stage']['jobs'][0]['experimentId'], 'experiment-1')
        state = ai.get_state(self.service, {'projectId': self.project_id})
        self.assertEqual(len(state['messages']), 2)
        self.assertEqual(state['messages'][1]['experimentIds'], ['experiment-1'])
        self.assertEqual(state['stageJobIds'], ['job-1'])

    def test_conversation_and_stage_follow_moved_project(self):
        proposal = dict(title='测试组合', description='待用户运行', spec=dict(projectId=self.project_id, kind='backtest.run', parameters={
            'template': 'multi_factor', 'factorIds': ['momentum20'], 'portfolio': {'method': 'risk_parity', 'grossExposure': .95}}))
        model = TestModel(call_tools=[], custom_output_args={'message': '已提出方案', 'phase': '组合比较', 'proposals': [proposal], 'experimentIds': []})
        with patch('pydantic_ai.models.openai.OpenAIChatModel', return_value=model):
            ai.chat(self.service, dict(projectId=self.project_id, mode='assist', message='配置风险平价'))
        ai.save_state(self.service, {'projectId': self.project_id, 'state': {'stageJobIds': ['running-1']}})
        self.service.close()
        moved = self.root / 'moved'
        Path(self.project['path']).rename(moved)
        other = Service(self.root / 'other-app')
        try:
            other.store.open_project(moved)
            restored = ai.get_state(other, {'projectId': self.project_id})
            self.assertEqual(restored['phase'], '组合比较')
            self.assertEqual(restored['messages'][0]['content'], '配置风险平价')
            self.assertEqual(restored['stageJobIds'], ['running-1'])
            self.assertEqual(restored['proposals'][0]['spec']['parameters']['portfolio']['method'], 'risk_parity')
        finally:
            other.close()

    def test_provider_failure_keeps_question_and_ask_never_runs_proposals(self):
        def unavailable(messages, info):
            raise RuntimeError('服务暂不可用')

        with patch('pydantic_ai.models.openai.OpenAIChatModel', return_value=FunctionModel(unavailable)):
            with self.assertRaisesRegex(RuntimeError, '服务暂不可用'):
                ai.chat(self.service, dict(projectId=self.project_id, mode='ask', message='解释回撤'))
        state = ai.get_state(self.service, {'projectId': self.project_id})
        self.assertEqual(state['messages'], [{'role': 'user', 'content': '解释回撤'}])
        model = TestModel(call_tools=[], custom_output_args={'message': '回复', 'phase': '问答', 'proposals': [], 'experimentIds': []})
        with patch('pydantic_ai.models.openai.OpenAIChatModel', return_value=model):
            ai.chat(self.service, dict(projectId=self.project_id, mode='ask', message='再试一次'))
        self.assertEqual(len(ai.get_state(self.service, {'projectId': self.project_id})['messages']), 3)
        self.assertEqual(self.service.store.list('job', self.project_id), [])


if __name__ == '__main__':
    unittest.main()
