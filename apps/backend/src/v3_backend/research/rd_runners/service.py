"""RD-Agent APIBackend using the selected service; secrets live only in globals."""
import json
import urllib.error
import urllib.request
import time

from rdagent.oai.backend.base import APIBackend

_service = {}
_local_embedding_path = None
_local_embedding_model = None
_last_provider_failure = None


class ProviderError(RuntimeError):
    def __init__(self,message,status_code=None):
        super().__init__(message)
        self.status_code=status_code


def last_provider_failure():
    return _last_provider_failure


def configure(service, local_embedding_path=None):
    global _service, _local_embedding_path, _last_provider_failure
    _last_provider_failure=None
    _service = dict(service)
    _local_embedding_path = local_embedding_path
    for key in ('baseUrl', 'model'):
        if not _service.get(key):
            raise ValueError('缺少模型服务配置: ' + key)


def redact(value):
    value = str(value)
    for source in (_service, _service.get('embedding', {})):
        secret = source.get('apiKey')
        if secret:
            value = value.replace(secret, '[redacted]')
    return value


def _post(settings, endpoint, payload):
    url = settings['baseUrl'].rstrip('/') + '/' + endpoint
    headers = {'Content-Type': 'application/json'}
    if settings.get('apiKey'):
        headers['Authorization'] = 'Bearer ' + settings['apiKey']
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    for attempt in range(3):
        delay=1.
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except InterruptedError:raise
        except urllib.error.HTTPError as exc:
            message='模型服务限流或当前配额不足，请稍后重试（HTTP 429）' if exc.code==429 else '模型服务HTTP错误: '+str(exc.code)
            if exc.code not in {408,429,500,502,503,504} or attempt==2:raise ProviderError(message,exc.code) from None
            retry=exc.headers.get('Retry-After','1') if exc.headers else '1'
            try:delay=max(0,float(retry))
            except (ValueError,TypeError):
                from email.utils import parsedate_to_datetime
                from datetime import datetime,timezone
                try:delay=max(0,(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                except (ValueError,TypeError):delay=1.
        except (urllib.error.URLError,TimeoutError,ConnectionError) as exc:
            if attempt==2:raise ProviderError('模型服务请求失败: '+type(exc).__name__) from None
        except Exception as exc:raise ProviderError('模型服务请求失败: '+type(exc).__name__) from None
        from .protocol import event
        event('model_request_retry',attempt=attempt+1,delaySeconds=delay)
        time.sleep(delay)


class V3APIBackend(APIBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(use_chat_cache=False, dump_chat_cache=False,
                         use_embedding_cache=False, dump_embedding_cache=False)

    def supports_response_schema(self):
        return False

    def _try_create_chat_completion_or_embedding(self,max_retry=1,chat_completion=False,embedding=False,*args,**kwargs):
        # Only _post retries temporary transport failures. Parsing, auth and code
        # failures must not restart the upstream whole request/repair loop.
        if chat_completion and not embedding:return self._create_chat_completion_auto_continue(*args,**kwargs)
        if embedding and not chat_completion:return self._create_embedding_with_cache(*args,**kwargs)
        raise ValueError('请选择模型或向量请求')

    def _calculate_token_from_messages(self, messages):
        import tiktoken
        # Conservative context budgeting only, never reported as provider usage.
        encoding = tiktoken.get_encoding('cl100k_base')
        return sum(len(encoding.encode(str(message.get('content', '')))) + 8 for message in messages)

    def _create_chat_completion_inner_function(self, messages, response_format=None, *args, **kwargs):
        global _last_provider_failure
        from .protocol import event
        payload = {'model': _service['model'], 'messages': messages, 'stream': False}
        if _service.get('temperature') is not None:
            payload['temperature'] = _service['temperature']
        if isinstance(response_format, dict) and 'ling' not in _service['model'].lower():
            payload['response_format'] = response_format
        elif response_format is not None:
            payload['messages'] = [dict(message) for message in messages] + [
                {'role':'user','content':'Return only valid JSON matching the exact JSON schema/format requested above. No commentary or Markdown fences.'}]
        event('model_request_started', model=_service['model'])
        _last_provider_failure=None
        try:
            response = _post(_service, 'chat/completions', payload)
        except ProviderError as exc:
            _last_provider_failure={'statusCode':exc.status_code,'message':str(exc)}
            event('model_request_failed',model=_service['model'],**_last_provider_failure)
            raise
        choice = response['choices'][0]
        content = choice['message'].get('content')
        if not isinstance(content, str) or not content.strip():
            raise ValueError('模型服务未返回文本内容')
        event('model_request_completed', model=_service['model'], usage=response.get('usage'))
        return content, choice.get('finish_reason')

    def _create_embedding_inner_function(self, input_content_list):
        global _local_embedding_model
        from .protocol import event
        if _local_embedding_path:
            from sentence_transformers import SentenceTransformer
            event('embedding_started', source='local', rows=len(input_content_list))
            if _local_embedding_model is None:
                _local_embedding_model = SentenceTransformer(_local_embedding_path, local_files_only=True)
                _local_embedding_model.max_seq_length = 1024
            values = _local_embedding_model.encode(input_content_list, normalize_embeddings=True).tolist()
            event('embedding_completed', source='local', rows=len(values), maxSequenceTokens=1024,
                  truncation='SentenceTransformer tokenizer truncates each text to at most 1024 tokens')
            return values
        settings = _service.get('embedding')
        if not settings or not settings.get('model') or not settings.get('baseUrl'):
            raise RuntimeError('原生CoSTEER知识检索需要真实embedding服务或已安装的本地embedding模型')
        event('embedding_started', source='service', rows=len(input_content_list))
        response = _post(settings, 'embeddings', {'model': settings['model'], 'input': input_content_list})
        rows = sorted(response['data'], key=lambda item: item['index'])
        if [item['index'] for item in rows] != list(range(len(input_content_list))):
            raise ValueError('Embedding服务返回行数/索引不匹配')
        event('embedding_completed', source='service', rows=len(rows))
        return [item['embedding'] for item in rows]
