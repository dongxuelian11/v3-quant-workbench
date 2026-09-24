import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v3_backend.research import reports, candidates
from v3_backend.research.storage import Store, identifier
from v3_backend.research.report_tasks import ReportTasks
from v3_backend.research.server import Service


class FakeJobs:
    def __init__(self, store):
        self.store, self.calls = store, []

    def submit(self, spec, frozen_project=None, *, submission_id=None):
        if submission_id:
            try:return self.store.get('job',submission_id)
            except ValueError:pass
        self.calls.append(deepcopy(spec))
        job = dict(id=submission_id or identifier(), kind=spec['kind'], spec=deepcopy(spec), projectId=spec.get('projectId'), status='queued', message='queued')
        self.store.put('job', job, spec.get('projectId') or '')
        return job

    def cancel(self, key):
        job = self.store.get('job', key)
        job['status'] = 'cancelled'
        return self.store.put('job', job, job.get('projectId') or '')


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'app')
        self.project = self.store.create_project(Path(self.tmp.name) / 'project', '研报测试')
        self.report = self.store.put('report', dict(id=identifier(), title='风格研究', institution='测试机构', symbols=['000001'],
                                                    publishedAt='2025-06-06', collectedAt='2026-09-20', source='test', documentAvailable=False))
        reports._save_pages(self.store, self.report, [{'page': 1, 'text': '原文：动量因子使用过去二十日收益。', 'method': 'text'}])
        self.jobs = FakeJobs(self.store)
        self.tasks = ReportTasks(SimpleNamespace(store=self.store, jobs=self.jobs))
        self.tasks.close()

    def tearDown(self):
        self.tasks.close()
        self.tmp.cleanup()

    def plan(self):
        step = dict(id='a', name='因子分析', variant='original', spec={'kind': 'factor.analyze', 'parameters': {'factorIds': ['momentum20'], 'startDate': '2025-07-01', 'endDate': '2025-12-31'}},
                    dependsOn=[], differences=[], citations=[{'reportId': self.report['id'], 'page': 1, 'excerpt': '过去二十日收益'}])
        dependent = {**deepcopy(step), 'id': 'b', 'dependsOn': ['a']}
        independent = {**deepcopy(step), 'id': 'c'}
        return self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': dict(reportId=self.report['id'], name='复现', steps=[step, dependent, independent])})

    def test_saved_plan_ui_requires_success_and_uses_persisted_values(self):
        from v3_backend.research.report_ai import validate_output
        plan = self.plan()
        service = SimpleNamespace(store=self.store, report_tasks=self.tasks)
        message = '解释保留。\n<root><ResearchStack>错误 UI</ResearchStack></root>\n条件仍需核对。'
        answer = {'message': message, 'uiBlocks': []}
        step = {'id': 'save-1', 'tool': 'save_reproduction_plan', 'status': 'completed',
                'planId': plan['id'], 'projectId': self.project['id'], 'planRevision': plan['revision']}
        for steps in ([], [{**step, 'status': 'failed'}], [{**step, 'planId': 'missing'}],
                      [{**step, 'planRevision': 999}], [{**step, 'projectId': 'unrelated'}]):
            result = validate_output(service, deepcopy(answer), self.project['id'], [], steps)
            self.assertEqual(result, answer)
        result = validate_output(service, deepcopy(answer), self.project['id'], [], [step, step])
        self.assertEqual(result['message'], '解释保留。\n\n条件仍需核对。')
        self.assertEqual(len(result['uiBlocks']), 1)
        block = result['uiBlocks'][0]
        self.assertEqual((block['reproductionId'], block['reproductionRevision']), (plan['id'], plan['revision']))
        self.assertEqual(block['experimentIds'], [])
        self.assertIn('ReportCitation(1, "过去二十日收益")', block['content'])
        self.assertIn('"startDate", "因子分析 · 开始日期", "2025-07-01"', block['content'])
        self.assertIn('ReproductionAction("保存参数并运行", true)', block['content'])
        self.assertNotIn('quantiles', block['content'])
        self.assertEqual(validate_output(service, deepcopy(answer), self.project['id'], [], [step]), result)
        plan['missingConditions'] = ['股票池待确认']
        self.store.project_store(self.project['id']).put('reproduction', plan, self.project['id'])
        blocked = validate_output(service, deepcopy(answer), self.project['id'], [], [step])['uiBlocks'][0]
        self.assertNotIn('保存参数并运行', blocked['content'])
        self.assertIn('股票池待确认', blocked['content'])
        self.assertEqual(self.jobs.calls, [])

    def test_saved_plan_ui_persists_after_live_tool_step(self):
        from pydantic_ai.models.test import TestModel
        from v3_backend.research import ai
        service = Service(Path(self.tmp.name) / 'execution-app')
        try:
            project = service.store.create_project(Path(self.tmp.name) / 'execution-project', '保存回放')
            service.store.put('report', self.report)
            service.store.settings = lambda: {'ai': {'baseUrl': 'http://127.0.0.1:1/v1', 'model': 'fixture'}}
            chat = service.request('ai.conversations.create', {'projectId': project['id']})
            factory = ai._create_agent
            def make_agent(svc, pid, model, *args, **kwargs):
                agent = factory(svc, pid, TestModel(), *args, **kwargs)
                async def run(*args, **kwargs):
                    agent._function_toolset.tools['save_reproduction_plan'].function(
                        {'reportId': self.report['id'], 'name': '实际工具保存', 'steps': [], 'missingConditions': ['待确认日期']})
                    return SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {
                        'message': '解释保留<root>错误控件</root>', 'uiBlocks': [], 'proposals': [], 'experimentIds': []}))
                return SimpleNamespace(run=run, tool_plain=agent.tool_plain)
            with patch.object(ai, '_create_agent', side_effect=make_agent):
                value = service.request('ai.chat.start', {'conversationId': chat['id'], 'requestId': identifier(), 'mode': 'assist', 'message': '保存草稿'})
                deadline = time.monotonic() + 10
                while value['status'] == 'running' and time.monotonic() < deadline:
                    time.sleep(.03)
                    value = service.executions.status({'conversationId': chat['id']})
            self.assertEqual(value['status'], 'completed', value.get('message'))
            message = service.request('ai.conversations.get', {'conversationId': chat['id']})['state']['messages'][-1]
            self.assertEqual(message['content'], '解释保留')
            block, = message['uiBlocks']
            saved_step = next(s for s in value['steps'] if s['tool'] == 'save_reproduction_plan')
            self.assertEqual(block['reproductionId'], saved_step['planId'])
            self.assertEqual(block['reproductionRevision'], saved_step['planRevision'])
            self.assertEqual(block['projectId'], saved_step['projectId'])
            self.assertEqual(service.store.list('job'), [])
        finally:
            service.close()

    def test_search_citations_and_document_boundaries(self):
        for keyword in ('动量因子', '动量'):
            found = reports.search(self.store, {'keyword': keyword})
            self.assertEqual(found['total'], 1)
        self.assertEqual(reports.search(self.store, {'keyword': '不存在'})['total'], 0)
        self.assertEqual(reports.search(self.store, {'symbol': 'SH600000'})['total'], 0)
        with self.assertRaisesRegex(ValueError, '摘录'):
            reports.validate_citations(self.store, [{'reportId': self.report['id'], 'page': 1, 'excerpt': '编造内容'}])
        with self.assertRaises(ValueError):
            reports._folder(self.store, '../escape')
        with patch.object(reports, '_download', return_value=b'<script>challenge</script>'):
            with self.assertRaisesRegex(ValueError, '有效 PDF'):
                reports.import_report(self.store, {'url': 'https://example.org/report.pdf'}, lambda *_: None)
        self.assertEqual(len(self.store.list('report')), 1)

    def test_dependencies_idempotency_resume_and_fixed_revision(self):
        plan = self.plan()
        params = {'projectId': self.project['id'], 'planId': plan['id']}
        run = self.tasks.dispatch('reproductions.run', params)
        self.assertEqual(len(self.jobs.calls), 2)
        again = self.tasks.dispatch('reproductions.run', params)
        self.assertEqual(run['runId'], again['runId'])
        for state in run['steps']:
            if state.get('jobId'):
                job = self.store.get('job', state['jobId'])
                job.update(status='failed' if state['stepId'] == 'a' else 'completed', experimentId='real-c' if state['stepId'] == 'c' else None)
                self.store.put('job', job, self.project['id'])
        self.tasks._advance(run)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['steps'][1]['status'], 'failed')
        self.assertNotIn('jobId', run['steps'][1])
        changed = self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': {**plan, 'name': '编辑后的版本'}})
        resumed = self.tasks.dispatch('reproductions.run', {**params, 'runId': run['runId'], 'retryFailed':True})
        self.assertEqual(resumed['revision'], 1)
        self.assertEqual(changed['revision'], 2)
        self.assertEqual(len(self.jobs.calls), 3)
        self.assertEqual(resumed['steps'][2]['experimentId'], 'real-c')
        a = self.store.get('job', resumed['steps'][0]['jobId'])
        a.update(status='completed', experimentId='real-a')
        self.store.put('job', a, self.project['id'])
        self.tasks._advance(resumed)
        self.assertEqual(len(self.jobs.calls), 4)
        self.assertEqual(resumed['steps'][1]['status'], 'queued')
        self.assertEqual(self.jobs.calls[-1]['reproduction']['revision'], 1)

    def test_cycle_publication_and_factor_without_strategy(self):
        plan = self.plan()
        plan['steps'][0]['dependsOn'] = ['b']
        with self.assertRaisesRegex(ValueError, '循环'):
            self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': plan})
        saved = candidates.save(self.store, self.project['id'], dict(kind='factor', name='独立因子',
                    spec={'kind': 'factor.analyze', 'parameters': {'factorIds': ['momentum20']}}))
        self.assertIsNone(saved['spec']['strategyId'])
        self.assertEqual(saved['projectId'], self.project['id'])
        from v3_backend.research.workbench import get_strategy
        get_strategy(self.store, self.project['id'], 'default')
        adopted = candidates.adopt(self.store, self.project['id'], saved['id'], 'default')
        self.assertIsNone(adopted['candidate'].get('strategyId'))
        self.assertEqual(adopted['candidate']['adoptedTarget']['strategyId'], 'default')

    def test_revision_publication_and_incremental_subscription(self):
        plan = self.plan()
        old = deepcopy(plan)
        plan['name'] = '新版'
        self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': plan})
        with self.assertRaisesRegex(ValueError, '新修订'):
            self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': old})
        with self.assertRaisesRegex(ValueError, '新修订'):
            self.tasks.dispatch('reproductions.run', {'projectId': self.project['id'], 'planId': old['id'], 'revision': 1})
        fresh = self.tasks.dispatch('reproductions.get', {'projectId': self.project['id'], 'planId': old['id']})
        fresh['steps'] = [fresh['steps'][0]]
        step = fresh['steps'][0]
        step.update(variant='post_publication', differences=['单独验证发布后区间'])
        step['spec'] = {'kind': 'model.train', 'parameters': {'model': 'ridge', 'factorIds': ['momentum20'], 'trainStart': '2024-01-01', 'trainEnd': '2024-06-30', 'validStart': '2024-07-01', 'validEnd': '2024-12-31', 'testStart': '2025-07-01', 'testEnd': '2025-12-31'}}
        fresh = self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': fresh})
        with self.assertRaisesRegex(ValueError, '不可用于训练或寻优'):
            self.tasks.dispatch('reproductions.run', {'projectId': self.project['id'], 'planId': fresh['id']})
        fresh['steps'][0]['spec'] = {'kind': 'factor.analyze', 'parameters': {'factorIds': ['momentum20'], 'startDate': '2024-01-01', 'endDate': '2026-12-31', 'testStart': '2026-01-01'}}
        fresh = self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': fresh})
        with self.assertRaisesRegex(ValueError, '晚于研报发布日期'):
            self.tasks.dispatch('reproductions.run', {'projectId': self.project['id'], 'planId': fresh['id']})
        value = {'id': identifier(), 'name': '增量', 'enabled': True, 'query': {'startDate': '2024-01-01', 'endDate': '2026-09-20'}, 'lastSuccessfulDate': '2026-09-18'}
        job = self.tasks._refresh_subscription(value)
        self.assertEqual(job['spec']['parameters']['startDate'], '2026-09-17')
        value['lastCheckedAt'] = '2026-09-20T00:00:00'
        self.jobs.cancel(job['id'])
        value['enabled'] = False
        self.tasks._subscription_tick(value)
        self.assertEqual(value['lastSuccessfulDate'], '2026-09-18')

    def test_ai_source_tools_and_narrow_ui_state(self):
        from v3_backend.research import ai
        from v3_backend.research.report_ai import validate_output
        from pydantic_ai.models.test import TestModel
        service = Service(Path(self.tmp.name) / 'ai-service')
        try:
            project = service.store.create_project(Path(self.tmp.name) / 'ai-project', 'AI测试')
            rid = identifier()
            report = service.store.put('report', dict(id=rid, title='真实原文', collectedAt='2026-09-20', symbols=[], source='test'))
            reports._save_pages(service.store, report, [{'page': 1, 'text': '原文使用二十日动量', 'method': 'text'}])
            agent = ai._create_agent(service, project['id'], TestModel(), execution=True)
            tools = agent._function_toolset.tools
            text = tools['read_report_pages'].function(rid, [1])
            self.assertEqual(text['pages'][0]['text'], '原文使用二十日动量')
            plan = tools['save_reproduction_plan'].function(dict(reportId=rid, name='有来源方案', missingConditions=['尚缺日期'], steps=[]))
            answer = {'reportCitations': [{'reportId': rid, 'page': 1, 'excerpt': '二十日动量'}],
                      'uiBlocks': [{'id': 'block-1', 'language': 'openui', 'content': 'ResearchText("原文")', 'reproductionId': plan['id']}]}
            validate_output(service, answer, project['id'], None)
            block = answer['uiBlocks'][0]
            self.assertEqual(block['reproductionRevision'], 1)
            self.assertEqual(block['reportId'], rid)
            service.store.put('conversation', {'id': 'chat-1', 'name': '测试', 'projectId': project['id'], 'context': [],
                 'state': {'messages': [{'id': 'message-1', 'role': 'assistant', 'uiBlocks': [block]}], 'stageJobIds': ['keep-job']}})
            service.request('ai.conversations.uiState', {'conversationId': 'chat-1', 'blockId': 'block-1', 'state': {'selected': 'a'}})
            saved = service.store.get('conversation', 'chat-1')['state']
            self.assertEqual(saved['stageJobIds'], ['keep-job'])
            self.assertEqual(saved['messages'][0]['uiBlocks'][0]['state'], {'selected': 'a'})
            ask = ai._create_agent(service, project['id'], TestModel(), execution=True, mode='ask')
            self.assertNotIn('save_reproduction_plan', ask._function_toolset.tools)
        finally:
            service.close()

    def test_library_copy_is_independent_and_ocr_install_uses_user_data(self):
        from v3_backend.research import candidate_library
        source = Path(self.project['path']) / 'factor.py'
        source.write_text('VALUE = 1\n', encoding='utf-8')
        value = candidates.save(self.store, self.project['id'], dict(kind='factor', name='源码因子',
                spec={'kind': 'factor.analyze', 'parameters': {'factorIds': ['custom'], 'customFactors': [{'id': 'custom', 'codePath': 'factor.py'}]}}))
        entry = candidate_library.dispatch(self.store, 'candidates.library.save', {'projectId': self.project['id'], 'candidateId': value['id']})
        other = self.store.create_project(Path(self.tmp.name) / 'second-project', '另一项目')
        imported = candidate_library.dispatch(self.store, 'candidates.library.import', {'projectId': other['id'], 'libraryId': entry['id']})
        self.assertNotEqual(imported['id'], value['id'])
        self.assertIsNone(imported.get('strategyId'))
        copied = Path(other['path']) / imported['spec']['parameters']['customFactors'][0]['codePath']
        copied.write_text('VALUE = 2\n', encoding='utf-8')
        self.assertEqual(source.read_text(encoding='utf-8'), 'VALUE = 1\n')
        library_code = self.store.root / 'shared/factor-library' / entry['id'] / entry['candidate']['spec']['parameters']['customFactors'][0]['codePath']
        self.assertEqual(library_code.read_text(encoding='utf-8'), 'VALUE = 1\n')
        child = SimpleNamespace(poll=lambda: 0, returncode=0)
        with patch('subprocess.Popen', return_value=child) as popen:
            reports.prepare_ocr(self.store, lambda *_: None)
        arguments = popen.call_args.args[0]
        destination = Path(arguments[arguments.index('--target') + 1])
        self.assertEqual(destination, self.store.root / 'shared/report-ocr-site')
        self.assertIn('creationflags', popen.call_args.kwargs)

    def test_model_and_strategy_library_require_explicit_destination(self):
        from v3_backend.research import candidate_library
        from v3_backend.research.workbench import get_strategy
        get_strategy(self.store, self.project['id'], 'default')
        other = self.store.create_project(Path(self.tmp.name) / 'library-target', '目标项目')
        get_strategy(self.store, other['id'], 'default')
        for kind, job_kind in [('model', 'model.train'), ('strategy', 'backtest.run')]:
            with self.subTest(kind=kind):
                value = candidates.save(self.store, self.project['id'], dict(kind=kind, name=kind, strategyId='default',
                    spec={'kind': job_kind, 'parameters': {'factorIds': ['momentum20'], 'codePath': kind + '.py'}}))
                source = Path(self.project['path']) / (kind + '.py')
                source.write_text('VALUE = 1\n', encoding='utf-8')
                entry = candidate_library.dispatch(self.store, 'candidates.library.save', {'projectId': self.project['id'], 'candidateId': value['id']})
                params = {'projectId': other['id'], 'libraryId': entry['id']}
                with self.assertRaisesRegex(ValueError, '明确选择目标研究策略'):
                    candidate_library.dispatch(self.store, 'candidates.library.import', params)
                with self.assertRaises(ValueError):
                    candidate_library.dispatch(self.store, 'candidates.library.import', {**params, 'strategyId': 'missing'})
                imported = candidate_library.dispatch(self.store, 'candidates.library.import', {**params, 'strategyId': 'default'})
                self.assertEqual(imported['kind'], kind)
                self.assertEqual(imported['strategyId'], 'default')
                self.assertEqual(imported['spec']['projectId'], other['id'])
                self.assertEqual(imported['spec']['strategyId'], 'default')
                self.assertNotEqual(imported['id'], value['id'])
                self.assertEqual(imported['experiments'], [])
                copied = Path(other['path']) / imported['spec']['parameters']['codePath']
                copied.write_text('VALUE = 2\n', encoding='utf-8')
                self.assertEqual(source.read_text(encoding='utf-8'), 'VALUE = 1\n')
                self.assertEqual(candidates.get(self.store, self.project['id'], value['id'])['revision'], value['revision'])

    def test_live_report_tool_steps_preserve_cancel_and_exclude_payloads(self):
        import asyncio
        from v3_backend.research import ai
        from pydantic_ai import ModelRetry
        from pydantic_ai.models.test import TestModel
        events = []
        service = Service(Path(self.tmp.name) / 'step-service', events.append)
        try:
            project = service.store.create_project(Path(self.tmp.name) / 'step-project', '步骤测试')
            rid, cid, eid = identifier(), identifier(), identifier()
            record = service.store.put('report', dict(id=rid, title='私有原文字样', collectedAt='2026-09-20', symbols=[], source='test'))
            reports._save_pages(service.store, record, [{'page': 1, 'text': '不得写入步骤的原文-secret-value', 'method': 'text'}])
            service.store.put('conversation', {'id': cid, 'projectId': project['id'], 'state': {'messages': [],
                'execution': {'id': eid, 'requestId': eid, 'status': 'running', 'steps': [], 'projectId': project['id']}}})
            agent = ai._create_agent(service, project['id'], TestModel(), conversation_id=cid, execution=True)
            tools = agent._function_toolset.tools
            actual_pages = reports.pages
            def checked_pages(*args):
                current = service.executions.status({'conversationId': cid})
                self.assertEqual(current['steps'][-1]['status'], 'running')
                self.assertEqual(current['steps'][-1]['pages'], [1])
                self.assertIn('读取报告页码', current['message'])
                return actual_pages(*args)
            with patch.object(reports, 'pages', side_effect=checked_pages):
                tools['read_report_pages'].function(rid, [1])
            with self.assertRaises(ModelRetry):
                tools['save_reproduction_plan'].function({'name': '不得记录的参数-secret-value'})
            plan = tools['save_reproduction_plan'].function({'reportId': rid, 'name': '方案', 'steps': [], 'missingConditions': ['缺日期']})
            with patch.object(reports, 'pages', side_effect=asyncio.CancelledError()):
                with self.assertRaises(asyncio.CancelledError):
                    tools['read_report_pages'].function(rid, [1])
            value = service.executions.status({'conversationId': cid})
            self.assertEqual([s['status'] for s in value['steps']], ['completed', 'failed', 'completed', 'cancelled'])
            self.assertEqual(value['steps'][1]['errorType'], 'ValueError')
            self.assertIn('reportId', value['steps'][1]['errorMessage'])
            self.assertEqual(value['steps'][1]['errorLocation']['function'], '_save_plan')
            self.assertIn(value['steps'][1]['errorMessage'], value['steps'][1]['summary'])
            self.assertEqual(value['steps'][2]['planId'], plan['id'])
            self.assertNotIn('secret-value', json.dumps(value['steps']))
            self.assertTrue(any('读取报告页码' in e.get('message', '') for e in events))
            service.executions.record_tools(cid, eid, [SimpleNamespace(parts=[SimpleNamespace(part_kind='tool-return', tool_name='read_report_pages', content={'text': 'secret-value'})])])
            self.assertFalse((Path(project['path']) / '.research/executions' / eid / 'tools.json').exists())
            service.executions.mutate(cid, eid, lambda state, v: v.update(status='cancelled', cancelRequested=True))
            with patch.object(reports, 'get') as read:
                with self.assertRaises(asyncio.CancelledError):
                    tools['read_report'].function(rid)
                read.assert_not_called()
            self.assertEqual(len(service.executions.status({'conversationId': cid})['steps']), 4)
            retry = SimpleNamespace(part_kind='retry-prompt', tool_name='save_reproduction_plan',
                                    content=[{'loc': ('plan', 'steps', 0, 'dependsOn'), 'input': 'secret-value', 'msg': 'secret-value', 'type': 'missing'}])
            service.executions.record_tools(cid, eid, [SimpleNamespace(parts=[retry])])
            latest = service.executions.status({'conversationId': cid})
            self.assertIn('plan.steps.0.dependsOn', latest['steps'][-1]['errorMessage'])
            self.assertIn('missing', latest['steps'][-1]['errorMessage'])
            self.assertNotIn('secret-value', json.dumps(latest['steps']))
        finally:
            service.close()

    def test_plan_tool_schema_and_safe_validation_reason(self):
        from v3_backend.research import ai
        from v3_backend.research.report_ai import validation_message, PlanInput
        from pydantic import TypeAdapter, ValidationError
        from pydantic_ai.models.test import TestModel
        from pydantic_ai import ModelRetry
        service = Service(Path(self.tmp.name) / 'schema-service')
        try:
            project = service.store.create_project(Path(self.tmp.name) / 'schema-project', '字段测试')
            rid = identifier()
            report = service.store.put('report', dict(id=rid, title='原文', collectedAt='2026-09-20', symbols=[], source='test'))
            reports._save_pages(service.store, report, [{'page': 5, 'text': '估值因子采用PE', 'method': 'text'}])
            agent = ai._create_agent(service, project['id'], TestModel(), execution=True)
            tool = agent._function_toolset.tools['save_reproduction_plan']
            schema = tool.function_schema.json_schema
            serialized = json.dumps(schema)
            for field in ('reportId', 'missingConditions', 'dependsOn', 'differences', 'citations', 'spec', 'variant', 'excerpt'):
                self.assertIn(field, serialized)
            plan = {'reportId': rid, 'name': 'PE适配', 'missingConditions': [], 'steps': [{'id': 'pe', 'name': 'PE', 'variant': 'adapted',
                'spec': {'kind': 'factor.analyze', 'parameters': {'factorIds': ['pe'], 'customFactors': [{'id': 'pe', 'expression': '$pettm'}], 'startDate': '2025-07-01', 'endDate': '2025-12-31'}},
                'dependsOn': [], 'differences': ['六股适配'], 'citations': [{'reportId': rid, 'page': 5, 'excerpt': '估值因子采用PE'}]}]}
            mapped = TypeAdapter(PlanInput).validate_python(plan)
            self.assertEqual(tool.function(mapped)['steps'][0]['spec']['parameters']['customFactors'][0]['expression'], '$pettm')
            plan['steps'][0]['citations'][0]['excerpt'] = '编造secret-key原文'
            with self.assertRaisesRegex(ModelRetry, '引用摘录与该页原文不符'):
                tool.function(plan)
            self.assertNotIn('secret', validation_message(ValueError('token=secret-key')))
            del plan['steps'][0]['dependsOn']
            with self.assertRaises(ValidationError):
                TypeAdapter(PlanInput).validate_python(plan)
        finally:
            service.close()

    def test_actual_ling_plan_payload_json_dates_and_pdf_whitespace(self):
        from pydantic import TypeAdapter, ValidationError
        from pydantic_ai import ModelRetry
        from pydantic_ai.models.test import TestModel
        from v3_backend.research import ai
        from v3_backend.research.report_ai import CompatiblePlanInput
        root = Path(__file__).resolve().parents[4]
        diagnostic = root / 'artifacts/round7-qa/ai-real/plan-tool-diagnostic.json'
        if not diagnostic.exists():
            self.skipTest('实际脱敏工具参数未提供')
        capture = json.loads(diagnostic.read_text(encoding='utf-8'))
        raw = json.loads(next(row['args'] for row in capture if row['part'] == 'tool-call'))
        self.assertIsInstance(raw['plan'], str)
        value = TypeAdapter(CompatiblePlanInput).validate_python(raw['plan'])
        self.assertNotIn('startDate', value['steps'][0]['spec']['parameters'])
        service = Service(Path(self.tmp.name) / 'replay-service')
        try:
            project = service.store.create_project(Path(self.tmp.name) / 'replay-project', '离线重放')
            reports.import_report(service.store, {'reportId': value['reportId'], 'filePath': str(root / 'artifacts/round7-qa/style-factor-report-20250606.pdf')}, lambda *_: None)
            citation = value['steps'][0]['citations'][0]
            page = reports.pages(service.store, {'reportId': value['reportId'], 'pages': [5]})['pages'][0]['text']
            self.assertNotIn(citation['excerpt'], page)
            reports.validate_citations(service.store, [citation])
            tool = ai._create_agent(service, project['id'], TestModel(), execution=True)._function_toolset.tools['save_reproduction_plan']
            wire = tool.function_schema.validator.validate_json(next(row['args'] for row in capture if row['part'] == 'tool-call'))
            self.assertIsInstance(wire['plan'], dict)
            self.assertEqual(wire['plan'], value)
            with self.assertRaisesRegex(ModelRetry, 'startDate/endDate'):
                tool.function(value)
            self.assertEqual(service.request('reproductions.list', {'projectId': project['id']}), [])
            # These dates were explicitly specified in the QA request, not inferred from prose.
            value['steps'][0]['spec']['parameters'].update(startDate='2025-06-09', endDate='2025-12-31')
            saved = tool.function(TypeAdapter(CompatiblePlanInput).validate_python(json.dumps(value, ensure_ascii=False)))
            self.assertEqual(saved['steps'][0]['spec']['parameters']['startDate'], '2025-06-09')
            wrong = deepcopy(citation)
            wrong['excerpt'] = wrong['excerpt'].replace('前10%', '前20%')
            with self.assertRaisesRegex(ValueError, '摘录'):
                reports.validate_citations(service.store, [wrong])
            for invalid in ('__import__("os").system("echo unsafe")', '[]', '{invalid-json}'):
                with self.assertRaises(ValidationError):
                    TypeAdapter(CompatiblePlanInput).validate_python(invalid)
        finally:
            service.close()

    def test_generated_files_and_native_model_copy_survive_missing_source(self):
        import pandas as pd
        from v3_backend.research import candidate_library, engines
        from v3_backend.research.workbench import get_strategy
        source_root = Path(self.project['path'])
        factor_file, predictions, events, code = [source_root / name for name in ('factor.parquet', 'predictions.parquet', 'training.parquet', 'model.py')]
        pd.DataFrame({'date': ['2025-01-02'], 'symbol': ['SH600000'], 'copyfactor': [1.25]}).to_parquet(factor_file)
        pd.DataFrame({'date': ['2025-01-02'], 'symbol': ['SH600000'], 'prediction': [2.5]}).to_parquet(predictions)
        pd.DataFrame({'epoch': [1], 'loss': [.2]}).to_parquet(events)
        code.write_text('VALUE = 1\n', encoding='utf-8')
        get_strategy(self.store, self.project['id'], 'default')
        factor = candidates.save(self.store, self.project['id'], {'kind': 'factor', 'name': '生成表',
            'spec': {'kind': 'factor.analyze', 'parameters': {'factorIds': ['copyfactor'], 'customFactors': [{'id': 'copyfactor', 'source': 'parquet', 'dataPath': factor_file.name}]}}})
        model = candidates.save(self.store, self.project['id'], {'kind': 'model', 'name': '原生模型', 'strategyId': 'default',
            'spec': {'kind': 'model.train', 'parameters': {'model': 'native_generated_predictions', 'factorIds': ['momentum20'],
                'codePath': code.name, 'dataPath': predictions.name, 'trainingEventsPath': events.name, 'nativeSourcePath': 'original-source.json', 'rdRequestId': 'old-request'}}})
        entries = [candidate_library.dispatch(self.store, 'candidates.library.save', {'projectId': self.project['id'], 'candidateId': v['id']}) for v in (factor, model)]
        for file in (factor_file, predictions, events, code):
            file.unlink()
        other = self.store.create_project(Path(self.tmp.name) / 'files-target', '文件副本')
        get_strategy(self.store, other['id'], 'default')
        imported_factor = candidate_library.dispatch(self.store, 'candidates.library.import', {'projectId': other['id'], 'libraryId': entries[0]['id']})
        path = imported_factor['spec']['parameters']['customFactors'][0]['dataPath']
        self.assertEqual(engines.generated_factor(other, Path(other['path']) / path, 'copyfactor').iloc[0, 0], 1.25)
        imported_model = candidate_library.dispatch(self.store, 'candidates.library.import', {'projectId': other['id'], 'libraryId': entries[1]['id'], 'strategyId': 'default'})
        params = imported_model['spec']['parameters']
        self.assertEqual(params['model'], 'native_torch')
        self.assertNotIn('nativeSourcePath', params)
        self.assertNotIn('rdRequestId', params)
        self.assertEqual(pd.read_parquet(Path(other['path']) / params['dataPath']).prediction.iloc[0], 2.5)
        self.assertEqual(pd.read_parquet(Path(other['path']) / params['trainingEventsPath']).loss.iloc[0], .2)
        self.assertTrue((Path(other['path']) / params['codePath']).is_file())
        self.assertIn('重新训练', imported_model['changeSummary'])
        self.assertEqual(imported_model['experiments'], [])

    def test_subscription_dates_download_failure_and_month_windows(self):
        subscription = self.tasks.dispatch('reports.subscriptions.save', {'subscription': {'name': '动量', 'enabled': False,
                      'query': {'keyword': '动量', 'startDate': '2025-01-15', 'endDate': '2025-03-02'}}})
        job = self.tasks.dispatch('reports.subscriptions.refresh', {'subscriptionId': subscription['id']})
        params = job['spec']['parameters']
        self.assertEqual(params['startDate'], '2025-01-15')
        self.assertTrue(params['collectDocuments'])
        response = {'TotalPage': 1, 'data': [{'title': '动量研究', 'orgSName': '测试', 'infoCode': 'AP20250115001', 'publishDate': '2025-01-15'}]}
        calls = []
        def download(url, *args):
            calls.append(url)
            return json.dumps(response).encode() if 'reportapi' in url else b'<script>challenge</script>'
        with patch.object(reports, '_download', side_effect=download):
            result = reports.refresh(self.store, params, lambda *_: None)
        catalogue_calls = [url for url in calls if 'reportapi' in url]
        self.assertEqual(len(catalogue_calls), 9)
        self.assertIn('endTime=2025-01-31', catalogue_calls[0])
        self.assertGreater(result['documentFailures'], 0)
        self.assertEqual(reports.get(self.store, 'eastmoney-AP20250115001')['extractionStatus'], 'failed')

    def test_real_pdf_job_and_source_page_search(self):
        pdf = Path(__file__).resolve().parents[4] / 'artifacts/round7-qa/style-factor-report-20250606.pdf'
        if not pdf.exists():
            self.skipTest('公开研报验收样本未提供')
        service = Service(Path(self.tmp.name) / 'real-service')
        try:
            job = service.request('reports.import', {'filePath': str(pdf), 'title': '风格制胜3'})
            deadline = time.monotonic() + 30
            while job['status'] in {'queued', 'running'} and time.monotonic() < deadline:
                time.sleep(.1)
                job = service.store.get('job', job['id'])
            self.assertEqual(job['status'], 'completed', job.get('message'))
            found = service.request('reports.search', {'keyword': '因子'})
            self.assertEqual(found['total'], 1)
            report = found['items'][0]
            self.assertGreater(report['pageCount'], 1)
            self.assertTrue(Path(service.request('reports.document', {'reportId': report['id']})['path']).is_file())
            self.assertTrue(service.store.experiment(None, job['experimentId']))
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main()
