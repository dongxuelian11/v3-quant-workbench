"""Storage display and explicit removal of unreferenced computation caches."""
import json
import shutil
from pathlib import Path


def _size(folder, check=lambda:None):
    total=0
    if not folder.exists():return total
    for path in folder.rglob('*'):
        check()
        if path.is_file() and not path.is_symlink():total+=path.stat().st_size
    return total


def _references(value, cache, owner):
    if isinstance(value,dict):return any(_references(x,cache,owner) for x in value.values())
    if isinstance(value,list):return any(_references(x,cache,owner) for x in value)
    if not isinstance(value,str):return False
    try:
        path=Path(value)
        if not path.is_absolute():path=owner/path
        resolved=path.resolve()
        return resolved==cache or resolved.is_relative_to(cache)
    except (ValueError,OSError):return False


def cache_references(store,project_id,cache):
    references=[]
    scopes=[(store,Path(store.project(None)['path'])),(store.project_store(None),Path(store.project(None)['path']))]
    for registered in store.list('project'):
        scopes.append((store.project_store(registered['id']),Path(registered['path'])))
    for portable,owner in scopes:
        with portable.connect() as db:
            for kind,key,body in db.execute('SELECT kind,id,body FROM records'):
                if kind not in {'experiment','candidate','strategy','simulation_account','daily_plan','screener','candidate_library'}:continue
                if _references(json.loads(body),cache,owner):references.append(dict(kind=kind,id=key))
    root=Path(store.project(project_id)['path'])/'.research/runs'
    for path in root.glob('*/project.json'):
        try:body=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            references.append(dict(kind='unreadable-experiment',id=path.parent.name));continue
        if _references(body,cache,Path(store.project(project_id)['path'])):references.append(dict(kind='experiment-input',id=path.parent.name))
    return references


def dispatch(service,method,params):
    store=service.store
    if method=='storage.inspect':
        from .data import project_data
        results=[];seen=set()
        for project_id in [None]+[p['id'] for p in store.list('project')]:
            service.check_read_cancel()
            try:project=store.project(project_id)
            except ValueError:
                results.append(dict(projectId=project_id,status='unavailable'));continue
            root=Path(project['path']);cache=root/'.research/cache'
            sections={}
            for name,path in [('data',Path(project_data(project)['path'])/'data'),('experiments',root/'.research/runs'),
                              ('cache',cache),('exports',root/'exports')]:
                resolved=str(path.resolve())
                sections[name]=dict(bytes=0 if resolved in seen else _size(path,service.check_read_cancel),shared=resolved in seen)
                seen.add(resolved)
            results.append(dict(projectId=project_id,name=project['name'],path=str(root),status='ready',categories=sections))
        return results
    if method=='storage.clearCache':
        project_id=params.get('projectId');project=store.project(project_id)
        root=Path(project['path']).resolve();cache=root/'.research/cache'
        if cache.resolve()!=cache or not cache.resolve().is_relative_to(root):raise ValueError('缓存目录不是此项目的普通缓存目录')
        # Submission/start share this lock, so new work cannot begin during removal.
        with service.jobs.lock:
            def uses_project(value):
                if isinstance(value,list):return any(uses_project(x) for x in value)
                if not isinstance(value,dict):return False
                if 'projectId' in value and value['projectId']==project_id:return True
                if value.get('path') and Path(value['path']).resolve()==root:return True
                return any(uses_project(x) for x in value.values())
            pending=[j for j in store.list('job') if uses_project(j) and
                     (j['status'] in {'queued','running','interrupted'} or j.get('registrationPending') or j.get('cleanupPending'))]
            if pending:raise ValueError('该项目仍有运行、待恢复或未确认停止的任务，缓存保留')
            refs=cache_references(store,project_id,cache)
            if refs:return dict(cleared=False,bytes=0,references=refs,message='研究产物仍引用缓存，已保留')
            count=_size(cache)
            if cache.exists():shutil.rmtree(cache)
            return dict(cleared=True,bytes=count,references=[],message='已清理可重建计算缓存；行情、输入、实验和对话保持不变')
    raise ValueError('未知存储操作')
