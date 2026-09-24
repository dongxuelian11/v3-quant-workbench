"""Shared public report catalogue and locally extracted, page-addressable PDFs."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .storage import identifier, now, read_json, write_json

MAX_PDF_BYTES = 80 * 1024 * 1024


def _index(store):
    with store.connect() as db:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS report_text USING fts5(report_id UNINDEXED, page UNINDEXED, text, tokenize='trigram')")


def get(store, report_id):
    return store.get('report', report_id)


def _folder(store, report_id):
    if not isinstance(report_id, str) or not re.fullmatch(r'(?:[0-9a-f]{32}|eastmoney-AP[0-9]+)', report_id):
        raise ValueError('研报 ID 无效')
    try:
        from .storage_migration import resolve_location
        return resolve_location(store.get('report_location',report_id)['path'],store.settings().get('_dataLocations',[]))
    except ValueError:
        legacy=store.root/'shared'/'reports'/report_id
        from .storage_migration import resolve_location
        legacy=resolve_location(legacy,store.settings().get('_dataLocations',[]))
        folder=legacy if legacy.exists() else store.data_root()/'reports'/report_id
        store.put('report_location',dict(id=report_id,path=str(folder)))
        return folder


def document(store, report_id):
    get(store, report_id)
    path = _folder(store, report_id) / 'document.pdf'
    if not path.is_file():
        raise ValueError('研报 PDF 尚未导入，请下载或选择本地文件')
    return {'path': str(path)}


def pages(store, params):
    report_id = params['reportId']
    get(store, report_id)
    items = read_json(_folder(store, report_id) / 'pages.json', [])
    selected = params.get('pages')
    if selected is not None:
        if not isinstance(selected, list) or any(type(p) is not int or p < 1 for p in selected):
            raise ValueError('页码必须为从 1 开始的整数数组')
        items = [p for p in items if p['page'] in selected]
    total = len(items)
    offset = max(0, int(params.get('offset', 0)))
    limit = max(1, min(50, int(params.get('limit', 20))))
    return {'reportId': report_id, 'pages': items[offset:offset + limit], 'total': total}


def validate_citations(store, citations):
    if not isinstance(citations, list):
        raise ValueError('引用必须为数组')
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError('引用格式无效')
        found = pages(store, {'reportId': citation['reportId'], 'pages': [citation['page']]})['pages']
        if not found or not found[0]['text'].strip():
            raise ValueError('引用页没有可读取原文，请先提取文字或执行 OCR')
        if citation.get('excerpt') and re.sub(r'\s+', '', citation['excerpt']) not in re.sub(r'\s+', '', found[0]['text']):
            raise ValueError('引用摘录与该页原文不符')
    return citations


def _save_pages(store, report, items):
    _index(store)
    # SQLite is the searchable copy; the JSON file also preserves extraction method.
    write_json(_folder(store, report['id']) / 'pages.json', items)
    with store.connect() as db:
        db.execute('DELETE FROM report_text WHERE report_id=?', (report['id'],))
        db.executemany('INSERT INTO report_text VALUES (?,?,?)',
                       [(report['id'], p['page'], p['text']) for p in items])
    empty = sum(not p['text'].strip() for p in items)
    report.update(pageCount=len(items), extractionStatus='needs_ocr' if empty else 'ready',
                  message=f'{empty} 页未提取到文字，可明确选择这些页执行 OCR' if empty else '已提取原文；图表解释仍需核对 PDF')
    return store.put('report', report)


def search(store, params):
    _index(store)
    query = str(params.get('keyword') or '').strip()
    matched = set()
    if query:
        with store.connect() as db:
            # FTS trigram indexes Chinese without requiring word boundaries.
            if len(query) >= 3:
                matched = {r[0] for r in db.execute('SELECT DISTINCT report_id FROM report_text WHERE report_text MATCH ?',
                                                    ('"' + query.replace('"', '""') + '"',))}
            else:
                matched = {r[0] for r in db.execute('SELECT DISTINCT report_id FROM report_text WHERE instr(text,?)>0', (query,))}
    result = []
    for report in store.list('report'):
        if query and query.casefold() not in report['title'].casefold() and report['id'] not in matched:
            continue
        if params.get('institution') and params['institution'].casefold() not in report.get('institution', '').casefold():
            continue
        if params.get('symbol') and params['symbol'][-6:] not in [s[-6:] for s in report['symbols']]:
            continue
        published = report.get('publishedAt') or ''
        if params.get('startDate') and published < params['startDate']:
            continue
        if params.get('endDate') and published > params['endDate']:
            continue
        result.append(report)
    result.sort(key=lambda r: (r.get('publishedAt') or '', r['collectedAt']), reverse=True)
    offset = max(0, int(params.get('offset', 0)))
    limit = max(1, min(200, int(params.get('limit', 50))))
    return {'items': result[offset:offset + limit], 'total': len(result)}


def _download(url, maximum=MAX_PDF_BYTES):
    parsed = urlparse(url)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('请输入公开的 HTTP 或 HTTPS 链接')
    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
        body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError('文件超过 80 MB，请使用较小的 PDF')
    return body


def import_report(store, params, progress):
    source = params.get('filePath')
    url = params.get('pdfUrl') or params.get('url')
    if bool(source) == bool(url):
        raise ValueError('请选择一个 PDF 文件或一个公开链接')
    progress(.1, '读取研报 PDF')
    if source:
        path = Path(source)
        if path.stat().st_size > MAX_PDF_BYTES:
            raise ValueError('文件超过 80 MB')
        body = path.read_bytes()
    else:
        body = _download(url)
        if not body.startswith(b'%PDF-') and 'data.eastmoney.com/report/' in url:
            # The upstream detail page declares a JSON attach_url; never evaluate scripts.
            match = re.search(r'"attach_url"\s*:\s*"([^"\r\n]+)"', body.decode('utf-8', errors='replace'))
            if match:
                url = json.loads('"' + match.group(1) + '"')
                body = _download(url)
        parsed = urlparse(url)
        if not body.startswith(b'%PDF-') and parsed.scheme == 'https' and parsed.hostname == 'pdf.dfcfw.com' and re.fullmatch(r'/pdf/H3_AP[0-9]+_1\.pdf', parsed.path):
            # This public upstream serves some PDFs only over its published HTTP endpoint.
            fallback = parsed._replace(scheme='http', query='', fragment='').geturl()
            alternate = _download(fallback)
            if alternate.startswith(b'%PDF-'):
                url, body = fallback, alternate
    if not body.startswith(b'%PDF-'):
        raise ValueError('来源未返回有效 PDF，可能是验证页面；请在浏览器下载后导入本地文件')
    report_id = params.get('reportId') or identifier()
    try:
        report = get(store, report_id)
    except ValueError:
        report = dict(id=report_id, title=params.get('title') or (Path(source).stem if source else '导入研报'),
                      symbols=[], collectedAt=now(), source='file/import' if source else 'url/import')
    for key in ('title', 'institution', 'authors', 'symbols', 'publishedAt'):
        if key in params:
            report[key] = params[key]
    if url:
        report.update(pdfUrl=url, url=params.get('url') or report.get('url') or url)
    folder = _folder(store, report_id)
    folder.mkdir(parents=True, exist_ok=True)
    import pdfplumber
    import io
    items = []
    # Parse before replacing a previously usable cached document.
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ''
            items.append({'page': number, 'text': text, 'method': 'text' if text.strip() else 'unavailable'})
            progress(.1 + .85 * number / max(1, len(pdf.pages)), f'提取第 {number}/{len(pdf.pages)} 页')
    temporary = folder / (identifier() + '.pdf')
    temporary.write_bytes(body)
    temporary.replace(folder / 'document.pdf')
    report.update(documentAvailable=True, extractionStatus='pending')
    return _save_pages(store, report, items)


def ocr(store, params, progress):
    report = get(store, params['reportId'])
    selected = params.get('pages')
    if not isinstance(selected, list) or not selected or any(type(p) is not int or p < 1 or p > report.get('pageCount', 0) for p in selected):
        raise ValueError('请明确选择 PDF 中需要 OCR 的页码')
    try:
        import sys
        ocr_site = store.root / 'shared' / 'report-ocr-site'
        if not ocr_site.is_dir():
            ocr_site = Path(sys.prefix) / 'report-ocr-site'
        if ocr_site.is_dir():
            sys.path.insert(0, str(ocr_site))
        from rapidocr_onnxruntime import RapidOCR
        import pypdfium2
        import numpy as np
    except ImportError as exc:
        prepare_ocr(store, progress)
        from rapidocr_onnxruntime import RapidOCR
        import pypdfium2
        import numpy as np
    engine = RapidOCR()
    items = read_json(_folder(store, report['id']) / 'pages.json', [])
    selected = sorted(set(selected))
    with pypdfium2.PdfDocument(document(store, report['id'])['path']) as pdf:
        for index, number in enumerate(selected):
            page = pdf[number - 1]
            bitmap = page.render(scale=2)
            try:
                result, _ = engine(np.asarray(bitmap.to_pil().convert('RGB')))
            finally:
                bitmap.close()
                page.close()
            text = '\n'.join(row[1] for row in (result or []))
            # An empty OCR result must not erase available native text.
            if text.strip():
                items[number - 1] = {'page': number, 'text': text, 'method': 'ocr'}
            progress((index + 1) / len(selected), f'OCR 第 {number} 页')
    return _save_pages(store, report, items)


def prepare_ocr(store, progress):
    """Only called by an explicitly requested OCR Job; cancellation kills its child."""
    import subprocess
    import sys
    import time
    destination = store.root / 'shared' / 'report-ocr-site'
    destination.mkdir(parents=True, exist_ok=True)
    log_path = destination / 'install.log'
    progress(.02, '首次准备本地 OCR 组件，正在下载；可取消任务')
    with log_path.open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                                  '--no-cache-dir', '--use-deprecated=legacy-certs', '--timeout', '15', '--retries', '1',
                                  '--index-url', 'https://pypi.org/simple', '--target', str(destination), '--upgrade',
                                  'rapidocr-onnxruntime==1.4.4', 'numpy>=1.26,<2', 'opencv-python<4.12'],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        while child.poll() is None:
            if time.monotonic() - started > 600:
                child.kill()
                child.wait()
                raise ValueError('OCR 组件下载超时，可稍后重试；原文保留')
            progress(.04, '正在准备 OCR 组件与内置中文模型')
            time.sleep(1)
    if child.returncode:
        raise ValueError('OCR 组件准备失败，请检查网络后重试；原文保留')
    if str(destination) not in sys.path:
        sys.path.insert(0, str(destination))


def refresh(store, params, progress):
    today = date.today()
    start = params.get('startDate') or (today - timedelta(days=365)).isoformat()
    end = params.get('endDate') or today.isoformat()
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('研报起止日期顺序无效')
    kinds = [0] if params.get('symbol') else [2, 1, 0]
    windows = []
    cursor, last = date.fromisoformat(start), date.fromisoformat(end)
    while cursor <= last:
        following = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        stop = min(last, following - timedelta(days=1))
        windows.append((cursor.isoformat(), stop.isoformat()))
        cursor = stop + timedelta(days=1)
    requests = [(kind, left, right) for kind in kinds for left, right in windows]
    checkpoint_id = params.get('_refreshId')
    checkpoint = None
    if checkpoint_id:
        try:
            checkpoint = store.get('report_refresh', checkpoint_id)
        except ValueError:
            pass
    scope = {key: params.get(key) for key in ('keyword', 'institution', 'symbol', 'startDate', 'endDate', 'collectDocuments')}
    if checkpoint and checkpoint.get('scope') != scope:
        checkpoint = None
    count = downloaded = failed = 0
    for request_index, (kind, left, right) in enumerate(requests):
        if checkpoint and request_index < checkpoint['requestIndex']:
            continue
        page = checkpoint['page'] if checkpoint and request_index == checkpoint['requestIndex'] else 1
        total = page
        while page <= total:
            query = dict(qType=kind, beginTime=left, endTime=right, pageNo=page, pageSize=100,
                         code=str(params.get('symbol') or '')[-6:], orgCode='', industryCode='*')
            payload = json.loads(_download('https://reportapi.eastmoney.com/report/list?' + urlencode(query), 10 * 1024 * 1024))
            rows = payload.get('data')
            if not isinstance(rows, list) or 'TotalPage' not in payload:
                raise ValueError('公开研报目录响应格式改变，已收录记录保留')
            total = int(payload['TotalPage'])
            if total > 500:
                raise ValueError('目录范围超过 500 页，请缩小日期范围；已收录记录保留')
            for row in rows:
                title = row.get('title') or row.get('reportTitle') or ''
                institution = row.get('orgSName') or ''
                if params.get('keyword') and params['keyword'].casefold() not in title.casefold():
                    continue
                if params.get('institution') and params['institution'].casefold() not in institution.casefold():
                    continue
                code = row.get('infoCode')
                if not code:
                    continue
                key = 'eastmoney-' + code
                try:
                    report = get(store, key)
                except ValueError:
                    report = dict(id=key, collectedAt=now(), documentAvailable=False, extractionStatus='pending')
                report.update(title=title, institution=institution, symbols=[row['stockCode']] if row.get('stockCode') else [],
                              publishedAt=str(row.get('publishDate') or '')[:10] or None, source='eastmoney/report',
                              url=f'https://data.eastmoney.com/report/zw_stock.jshtml?infocode={code}',
                              pdfUrl=f'https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf')
                store.put('report', report)
                count += 1
                if params.get('collectDocuments') and not report['documentAvailable']:
                    try:
                        import_report(store, {'reportId': key, 'pdfUrl': report['pdfUrl']}, progress)
                        downloaded += 1
                    except Exception as exc:
                        failed += 1
                        report.update(extractionStatus='failed', message='原文收集未成功：' + str(exc)[:250])
                        store.put('report', report)
            progress(min(.95, (request_index + page / max(1, total)) / len(requests)), f'公开目录 {left} 至 {right} 类型 {kind}：第 {page}/{total} 页，收录 {count} 条')
            page += 1
            if checkpoint_id:
                store.put('report_refresh', dict(id=checkpoint_id, scope=scope, requestIndex=request_index if page <= total else request_index + 1, page=page if page <= total else 1))
    if checkpoint_id:
        store.delete('report_refresh', checkpoint_id)
    return {'collected': count, 'downloaded': downloaded, 'documentFailures': failed, 'startDate': start, 'endDate': end,
            'message': f'公开目录刷新完成；原文下载 {downloaded}，未成功 {failed}；未调用 AI'}


def execute(store, kind, params, progress):
    result = {'reports.import': import_report, 'reports.ocr': ocr, 'reports.refresh': refresh}[kind](store, params, progress)
    return dict(metrics={}, artifacts=[], summary={'reports.import': '研报导入完成', 'reports.ocr': '研报 OCR 完成', 'reports.refresh': '研报目录刷新完成'}[kind], details=result)
