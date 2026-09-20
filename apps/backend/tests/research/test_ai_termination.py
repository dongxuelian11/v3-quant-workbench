"""Offline OpenAI wire checks: tool result delivery and valid final answer routes."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from v3_backend.research import ai, reports
from v3_backend.research.server import Service
from v3_backend.research.storage import identifier


class TerminationTests(unittest.TestCase):
    def test_required_loop_and_text_or_structured_termination_on_same_wire(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as root:
                service = Service(root)
                rid = identifier()
                original_text = '第5页原文：估值因子采用市盈率。' * 500
                report = service.store.put('report', dict(id=rid, title='受控研报', collectedAt='2026-09-20', symbols=[], source='fixture'))
                reports._save_pages(service.store, report, [{'page': 5, 'text': original_text, 'method': 'text'}])
                try:
                    for mode in ('legacy_required', 'text', 'structured'):
                        calls = []
                        def wire(request):
                            body = json.loads(request.content)
                            calls.append(body)
                            returned = [m for m in body['messages'] if m['role'] == 'tool']
                            if returned:
                                self.assertEqual(returned[-1]['tool_call_id'], 'read-' + str(len(calls) - 1))
                                self.assertEqual(json.loads(returned[-1]['content'])['pages'][0]['text'], original_text)
                            if not returned or body['tool_choice'] == 'required':
                                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'read-' + str(len(calls)), 'type': 'function',
                                    'function': {'name': 'read_report_pages', 'arguments': json.dumps({'report_id': rid, 'pages': [5]})}}]}
                                reason = 'tool_calls'
                            elif mode == 'structured':
                                self.assertIn('final_answer', [t['function']['name'] for t in body['tools']])
                                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'finish', 'type': 'function',
                                    'function': {'name': 'final_answer', 'arguments': json.dumps({'message': '第5页使用市盈率。', 'phase': '', 'proposals': [],
                                        'reportCitations': [{'reportId': rid, 'page': 5, 'excerpt': '估值因子采用市盈率'}]})}}]}
                                reason = 'tool_calls'
                            else:
                                message = {'role': 'assistant', 'content': '第5页使用市盈率。'}
                                reason = 'stop'
                            return httpx.Response(200, json={'id': 'mock-completion', 'object': 'chat.completion', 'created': 1,
                                'model': 'inclusionai/ling-3.0-flash-fin:free', 'choices': [{'index': 0, 'finish_reason': reason, 'message': message}],
                                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})
                        client = AsyncOpenAI(api_key='offline-test-key', base_url='https://offline.invalid/v1',
                                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))
                        try:
                            model = OpenAIChatModel('inclusionai/ling-3.0-flash-fin:free', provider=OpenAIProvider(openai_client=client))
                            if mode == 'legacy_required':
                                class Answer(BaseModel):
                                    message: str
                                agent = Agent(model, output_type=ToolOutput(Answer, strict=False))
                                @agent.tool_plain
                                def read_report_pages(report_id: str, pages: list[int]) -> dict:
                                    return reports.pages(service.store, {'reportId': report_id, 'pages': pages})
                                with self.assertRaises(UsageLimitExceeded):
                                    await agent.run('读取第5页后回答', usage_limits=UsageLimits(request_limit=3))
                                self.assertEqual(len(calls), 3)
                                self.assertTrue(all(c['tool_choice'] == 'required' for c in calls))
                            else:
                                agent = ai._create_agent(service, None, model, mode='ask')
                                response = await agent.run('读取第5页后回答', usage_limits=UsageLimits(request_limit=3))
                                answer = response.output.model_dump()
                                self.assertEqual(answer['message'], '第5页使用市盈率。')
                                self.assertEqual(answer['proposals'], [])
                                self.assertEqual(answer['experimentIds'], [])
                                self.assertEqual(len(calls), 2)
                                self.assertTrue(all(c['tool_choice'] == 'auto' for c in calls))
                                self.assertEqual(len(answer['reportCitations']), 1 if mode == 'structured' else 0)
                        finally:
                            await client.close()
                finally:
                    service.close()
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
