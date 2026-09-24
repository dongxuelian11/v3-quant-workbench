"""Copy and verify managed data before one settings-file switch. Sources are retained."""
from contextlib import contextmanager,closing,nullcontext
from contextvars import ContextVar
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,threading
from .storage import read_json,write_json,identifier,now

_locations=ContextVar('physical_data_locations',default=None)
ACTIVE={'waiting','copying','verifying','switching'}


def resolve_location(path,locations=None):
    path=Path(path).resolve();seen=set()
    owner=_locations.get()
    entries=(owner.settings().get('_dataLocations',[]) if owner is not None else []) if locations is None else locations
    while True:
        key=os.path.normcase(str(path))
        if key in seen:raise ValueError('数据目录迁移关系循环，停止访问')
        seen.add(key)
        match=next((item for item in sorted(entries,key=lambda x:len(x['source']),reverse=True) if path.is_relative_to(Path(item['source']))),None)
        if match is None:return path
        path=Path(match['target'])/path.relative_to(Path(match['source']))


@contextmanager
def location_scope(store):
    token=_locations.set(store)
    try:yield
    finally:_locations.reset(token)


def _rows(path):
    if not path.is_file():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        return [(kind,key,json.loads(body)) for kind,key,body in db.execute('SELECT kind,id,body FROM records')]


def _linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0)&0x400)


def _digest(path,check=lambda:None):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):check();digest.update(chunk)
    return digest.hexdigest()


def _walk_paths(value,field=''):
    if isinstance(value,dict):
        for key,item in value.items():yield from _walk_paths(item,field+'.'+key if field else key)
    elif isinstance(value,list):
        for index,item in enumerate(value):yield from _walk_paths(item,field+'.'+str(index))
    elif isinstance(value,str):
        try:
            if Path(value).is_absolute():yield field,Path(value).resolve()
        except (ValueError,OSError):pass


def inventory(store,target_directory,owned=None,check=lambda:None):
    """Read only, including database access: no Store constructor or report-location backfill."""
    settings=store.settings();locations=settings.get('_dataLocations',[])
    raw_source=Path(settings.get('storage',{}).get('dataDirectory') or store.root/'shared')
    for parent in [raw_source,*raw_source.parents]:
        if parent.exists() and _linked(parent):raise ValueError('源目录或祖先包含链接或目录联接')
    source=store.data_root();raw=Path(target_directory)
    blockers=[]
    if not raw.is_absolute():raise ValueError('请选择绝对目标目录')
    target=raw.resolve();shared=store.root/'shared'
    for parent in [raw,*raw.parents]:
        if parent.exists() and _linked(parent):blockers.append('目标路径包含链接或目录联接');break
    app_rows=_rows(store.db);projects=[v for kind,_,v in app_rows if kind=='project']
    records=list(app_rows)
    for owner in [shared,*[Path(project['path']) for project in projects]]:
        if not owner.is_dir() and owner!=shared:blockers.append('已有项目目录不可访问：'+str(owner));continue
        records.extend(_rows(owner/'.research/research.sqlite'))
        project_json=owner/'project.json'
        if project_json.is_file():records.append(('project-file',str(owner),read_json(project_json)))
        for path in (owner/'.research/runs').glob('*/project.json'):
            records.append(('experiment-input',path.parent.name,read_json(path)))
    pairs=[]
    def add(kind,start,end):
        for parent in [Path(start),*Path(start).parents]:
            if parent.exists() and _linked(parent):blockers.append('原始来源路径包含链接或目录联接：'+str(start));return
        start=resolve_location(start,locations)
        if any(start.is_relative_to(Path(item['source'])) for item in pairs):return
        pairs.append(dict(kind=kind,source=str(start),target=str(end)))
    for name in ('data','reports'):add(name,source/name,target/name)
    if shared!=source:
        for name in ('data','reports'):add(name,shared/name,target/name)
    for name in ('quotes','minutes','market-snapshot'):add(name,shared/name,target/name)
    for kind,key,value in app_rows:
        if kind=='report_location':
            if not resolve_location(value['path'],locations).is_dir():blockers.append('已有研报目录不可访问：'+key)
            add('reports',Path(value['path']),target/'reports'/key)
    nested_sources=set()
    for project in projects:
        root=Path(project['path']).resolve()
        if target==root or target.is_relative_to(root):blockers.append('目标不能位于已有项目内')
        for pair in pairs:
            if root.is_relative_to(Path(pair['source'])):
                nested_sources.add(pair['source']);blockers.append('源数据目录包含已有项目 '+project.get('name',project['id'])+'，请先整理目录；不会复制项目或固定实验')
    if target==store.root or target.is_relative_to(store.root):blockers.append('目标不能位于应用配置目录内')
    for root in {source,shared,*[Path(item['source']) for item in pairs]}:
        if target==root or target.is_relative_to(root) or root.is_relative_to(target):blockers.append('源目录与目标目录不能相同或互相包含')
    marker=target/'.v3-data-copy.json'
    claimed=read_json(marker,{}) if marker.exists() and not _linked(marker) else {}
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        if not owned or claimed.get('migrationId')!=owned:blockers.append('目标必须为空，或是本次迁移的专属副本')
    files=[];destinations={};groups=[]
    for pair in pairs:
        root=Path(pair['source']);count=size=0
        if pair['source'] in nested_sources:
            groups.append({**pair,'files':0,'bytes':0});continue
        if root.exists():
            if not root.is_dir() or _linked(root):blockers.append('数据来源不是普通目录：'+str(root));continue
            safe_files=[]
            for directory,folders,names in os.walk(root,followlinks=False):
                check()
                for name in list(folders):
                    candidate=Path(directory)/name
                    if _linked(candidate):blockers.append('源目录含链接或目录联接：'+str(candidate));folders.remove(name)
                for name in names:
                    candidate=Path(directory)/name
                    if _linked(candidate):blockers.append('源目录含链接或目录联接：'+str(candidate))
                    elif candidate.is_file():safe_files.append(candidate)
            for path in sorted(safe_files):
                check()
                stat=path.stat();destination=Path(pair['target'])/path.relative_to(root)
                if str(destination) in destinations:
                    if _digest(path,check)!=_digest(Path(destinations[str(destination)]['source']),check):blockers.append('多个来源文件冲突：'+str(destination.relative_to(target)))
                    continue
                item=dict(source=str(path),target=str(destination),bytes=stat.st_size,mtime=stat.st_mtime_ns)
                files.append(item);destinations[str(destination)]=item;count+=1;size+=stat.st_size
        groups.append({**pair,'files':count,'bytes':size})
    references=[]
    for kind,key,value in records:
        check()
        for field,path in _walk_paths(value):
            resolved=resolve_location(path,locations)
            matched=any(resolved.is_relative_to(Path(pair['source'])) for pair in pairs)
            action='redirect' if matched else 'keep'
            reason='迁移后在实际数据访问处解析新物理目录' if matched else '项目、固定输入或外部自定义路径保留原位'
            if matched and field.rsplit('.',1)[-1] not in {'dataPath','inputDataRoot','path','sourceRoot','documentPath','frozenDataPath'}:
                action='blocked';reason='此绝对引用尚无明确的数据寻址接线';blockers.append(kind+' '+key+' 的路径需核对：'+field)
            references.append(dict(kind=kind,id=key,field=field,action=action,reason=reason))
    existing=target
    while not existing.exists():existing=existing.parent
    available=shutil.disk_usage(existing).free
    required=sum(item['bytes'] for item in files)
    remaining=sum(item['bytes'] for item in files if not (owned and Path(item['target']).is_file() and not _linked(Path(item['target'])) and Path(item['target']).stat().st_size==item['bytes'] and _digest(Path(item['target']),check)==_digest(Path(item['source']),check)))
    if owned and target.is_dir():
        expected={item['target'] for item in files}|{str(marker)}
        for path in target.rglob('*'):
            if _linked(path):blockers.append('目标副本出现链接或目录联接')
            elif path.is_file() and str(path) not in expected and not path.name.endswith('.migration-'+owned+'.tmp'):
                blockers.append('副本中存在来源已不再包含的文件，请核对后选择新目标')
    if available<remaining+max(1024*1024,remaining//100):blockers.append('目标磁盘可用空间不足')
    affected=[dict(id=key,name=value.get('name',key),status=value['status']) for kind,key,value in app_rows if kind=='job' and value.get('status') in {'queued','running'}]
    return dict(sourceDirectory=str(source),targetDirectory=str(target),requiredBytes=required,availableBytes=available,fileCount=len(files),canStart=not blockers,blockers=list(dict.fromkeys(blockers)),copyGroups=groups,references=references,affectedJobs=affected),files


def copy_verified(state,files,save,check=lambda:None):
    target=Path(state['targetDirectory'])
    for path in [target,*target.parents]:
        if path.exists() and _linked(path):raise ValueError('目标路径出现链接或目录联接')
    marker=target/'.v3-data-copy.json'
    if target.exists() and any(target.iterdir()) and (not marker.is_file() or read_json(marker,{}).get('migrationId')!=state['id']):raise ValueError('目标不是本次迁移的专属副本')
    target.mkdir(parents=True,exist_ok=True)
    if marker.exists() and read_json(marker).get('migrationId')!=state['id']:raise ValueError('目标副本不属于本次迁移')
    write_json(marker,dict(migrationId=state['id'],sourceDirectory=state['sourceDirectory']))
    state.update(status='copying',filesTotal=len(files),bytesTotal=sum(item['bytes'] for item in files),filesVerified=0,bytesCopied=0)
    save()
    for item in files:
        check();source=Path(item['source']);destination=Path(item['target'])
        if _linked(source):raise ValueError('复制期间来源变为链接')
        current=source.stat()
        if (current.st_size,current.st_mtime_ns)!=(item['bytes'],item['mtime']):raise ValueError('复制期间源文件已变化，请重试')
        digest=_digest(source,check)
        for parent in [destination,*destination.parents]:
            if parent.exists() and _linked(parent):raise ValueError('目标路径出现链接，停止复制')
            if parent==target:break
        if not destination.is_file() or _digest(destination,check)!=digest:
            destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.migration-'+state['id']+'.tmp')
            with source.open('rb') as src,temporary.open('wb') as dst:
                while chunk:=src.read(1024*1024):check();dst.write(chunk)
            if _digest(temporary,check)!=digest:raise ValueError('副本内容校验失败')
            temporary.replace(destination)
        if _digest(source,check)!=digest:raise ValueError('校验期间源文件已变化，请重试')
        state['filesVerified']+=1;state['bytesCopied']+=item['bytes'];state['message']='正在复制并验证数据文件';save()
    state.update(status='verifying',message='文件已逐一验证，等待停写与引用复核；尚未切换配置');save()


class MigrationManager:
    """One resumable copy per application; queue and request gates share this owner."""
    SAFE={'workspace.get','workspace.save','factors.list','settings.get','jobs.list','jobs.cancel','ai.chat.status','reads.cancel','projects.list','strategies.list','simulation.accounts.list','ai.conversations.list','workspace.project.get','jobs.recoverResult','experiments.list','experiments.get','experiments.table','experiments.analysis','experiments.calendar','experiments.compare','experiments.previousComparison','ai.conversations.get','ai.projectSummary.get','simulation.accounts.get','ai.chat.cancel'}
    def __init__(self,service):
        self.service=service;self.store=service.store;self.lock=threading.RLock();self.start_lock=threading.Lock()
        self.pause=threading.Event();self.stop=threading.Event();self.thread=None;self.active_requests=0
        self.cancel_requested=False
        try:self.state=self.store.get('storage_migration','active')
        except ValueError:self.state=None
        self.service.jobs.migration_pause=self.pause
        self.service.jobs.migration_manager=self
        if self.state and self.store.settings().get('_dataMigrationId')==self.state['id']:
            self.state.update(status='completed',message='目录切换已完成；已恢复完成状态',canResume=False);self._save()
        elif self.state and self.state['status'] not in {'completed','cancelled'}:
            self.pause.set();self.state.update(status='failed',message='上次迁移未完成；写入仍暂停，请继续或取消',canResume=True);self._save()

    def _save(self):
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO records(kind,id,project,body) VALUES('storage_migration','active','',?)",(json.dumps(self.state,ensure_ascii=False),))

    def status(self):
        with self.lock:
            if not self.state:return None
            fields=('id','status','sourceDirectory','targetDirectory','filesTotal','filesVerified','bytesTotal','bytesCopied','message','canResume','blockers','warnings')
            return {key:self.state[key] for key in fields}

    @contextmanager
    def request_scope(self,method,params=None):
        params=params or {}
        ask=method=='ai.chat.start' and params.get('mode')=='ask'
        if method=='ai.chat.message':
            try:ask=self.service.executions.status(params).get('mode')=='ask'
            except (ValueError,KeyError):pass
        from .reminders import READ_METHODS, MANAGEMENT_METHODS
        # Metadata-only reminder operations never access migrated price data.
        # checks remain gated so future live sources cannot bypass migration pause.
        if ask or method.startswith('storage.migration.') or method in self.SAFE or method in READ_METHODS | MANAGEMENT_METHODS:
            yield;return
        with self.lock:
            if self.pause.is_set():raise ValueError('数据目录迁移期间已暂停访问与写入，请在设置中继续或取消迁移')
            self.active_requests+=1
        try:yield
        finally:
            with self.lock:self.active_requests-=1

    def preview(self,params):return inventory(self.store,params['targetDirectory'],check=self.service.check_read_cancel)[0]

    def start(self,params):
        if not isinstance(params.get('requestId'),str) or not params['requestId']:raise ValueError('迁移请求缺少requestId')
        with self.start_lock:
            with self.lock:
                if self.state and self.state.get('requestId')==params['requestId']:
                    if Path(params['targetDirectory']).resolve()!=Path(self.state['targetDirectory']):raise ValueError('同一迁移请求不能更换目标')
                    return self.status()
                if self.pause.is_set():raise ValueError('已有未完成迁移，请继续或取消')
            preview,_=inventory(self.store,params['targetDirectory'],check=self.service.check_read_cancel)
            if not preview['canStart']:raise ValueError('；'.join(preview['blockers']))
            self.service.check_read_cancel()
            reports=getattr(self.service,'report_tasks',None)
            with reports.lock if reports else nullcontext(),self.service.jobs.lock,self.lock:
                if self.pause.is_set():raise ValueError('已有未完成迁移，请继续或取消')
                self.state=dict(id=identifier(),requestId=params['requestId'],status='waiting',sourceDirectory=preview['sourceDirectory'],targetDirectory=preview['targetDirectory'],
                    filesTotal=preview['fileCount'],filesVerified=0,bytesTotal=preview['requiredBytes'],bytesCopied=0,message='等待现有任务与缓存写入完成',canResume=False,blockers=[],warnings=['源目录将保留，项目与固定实验输入不移动'])
                self.pause.set();self._save();self._launch()
                return self.status()

    def _launch(self):
        self.cancel_requested=False;self.stop.clear()
        self.thread=threading.Thread(target=self._run,daemon=True,name='data-migration');self.thread.start()

    def _check(self):
        if self.stop.is_set() or self.cancel_requested:raise InterruptedError('迁移在切换前中断，源目录与原配置保留')

    def _wait_writers(self):
        from . import intraday,quotes
        while True:
            self._check()
            with self.service.jobs.lock:
                processes=bool(self.service.jobs.processes)
                jobs=self.store.list('job')
                pending=[j for j in jobs if j.get('cleanupPending') or j.get('registrationPending')]
                unconfirmed=bool(pending)
            with self.lock:requests=self.active_requests
            with intraday._lock:minutes=any(not future.done() for future in intraday._pending.values())
            with quotes._quote_lock:quote=any(not future.done() for future in quotes._quote_pending.values())
            waiting=[j.get('name',j['id'])+'（'+j['id']+'）：'+('请恢复结果登记' if j.get('registrationPending') else '请确认任务已停止') for j in pending]
            waiting.extend(j.get('name',j['id'])+'：等待正在执行的任务结束' for j in jobs if j['id'] in self.service.jobs.processes and j not in pending)
            if requests:waiting.append('等待已开始的请求完成')
            if minutes or quote:waiting.append('等待分钟线或报价缓存刷新结束')
            with self.lock:
                if self.state['blockers']!=waiting:
                    self.state.update(blockers=waiting,message='；'.join(waiting) if waiting else '写入已停止，开始检查数据');self._save()
            if not (processes or unconfirmed or requests or minutes or quote):return
            self.stop.wait(.1)

    def _run(self):
        try:
            self._wait_writers();self._check()
            preview,files=inventory(self.store,self.state['targetDirectory'],owned=self.state['id'],check=self._check)
            if not preview['canStart']:raise ValueError('；'.join(preview['blockers']))
            if preview['sourceDirectory']!=self.state['sourceDirectory']:raise ValueError('来源目录设置已变化，不能继续旧迁移')
            copy_verified(self.state,files,self._save,self._check)
            final,current=inventory(self.store,self.state['targetDirectory'],owned=self.state['id'],check=self._check)
            if not final['canStart'] or current!=files:raise ValueError('复制后来源或引用发生变化，未切换；请重试')
            for item in files:
                self._check()
                if _digest(Path(item['source']),self._check)!=_digest(Path(item['target']),self._check):raise ValueError('切换前最终内容校验失败')
            with self.lock:
                self._check();self.state.update(status='switching',message='校验完成，正在切换实际数据目录');self._save()
                if str(self.store.data_root())!=self.state['sourceDirectory']:raise ValueError('切换前来源配置已变化，未切换')
                settings=self.store.settings();locations=list(settings.get('_dataLocations',[]))
                for group in final['copyGroups']:
                    entry={key:group[key] for key in ('source','target')}
                    if entry not in locations:locations.append(entry)
                self.store.settings(dict(storage={**settings.get('storage',{}),'dataDirectory':self.state['targetDirectory']},_dataLocations=locations,_dataMigrationId=self.state['id']))
                self.state.update(status='completed',message='复制验证和目录切换完成；源目录保留',canResume=False);self._save();self.pause.clear()
            with self.service.jobs.lock:self.service.jobs._start_next(None)
        except Exception as exc:
            with self.lock:
                committed=self.store.settings().get('_dataMigrationId')==self.state['id']
                if committed:
                    self.state.update(status='completed',message='实际目录已切换，完成状态已恢复',canResume=False);self.pause.clear()
                elif self.cancel_requested:
                    self.state.update(status='cancelled',message='迁移已取消，源目录与原配置保留；副本保留',canResume=False);self.pause.clear()
                else:self.state.update(status='failed',message='迁移未切换：'+str(exc),canResume=True)
                self._save()
            if not self.pause.is_set():
                with self.service.jobs.lock:self.service.jobs._start_next(None)

    def resume(self,params):
        with self.service.jobs.lock,self.lock:
            self._require(params)
            if self.thread and self.thread.is_alive():return self.status()
            if self.state['status'] in {'completed','cancelled'}:raise ValueError('此迁移已结束')
            self.state.update(status='waiting',message='正在重新检查来源并继续复制',canResume=False);self.pause.set();self._save();self._launch();return self.status()

    def _require(self,params):
        if not self.state or params.get('migrationId')!=self.state['id']:raise ValueError('迁移记录不存在')

    def cancel(self,params):
        with self.lock:
            self._require(params)
            if self.state['status'] in {'switching','completed'}:raise ValueError('目录已开始切换，不能取消')
            self.cancel_requested=True
            if not self.thread or not self.thread.is_alive():
                self.state.update(status='cancelled',message='迁移已取消，原配置与源目录保留',canResume=False);self._save();self.pause.clear()
        if not self.pause.is_set():
            with self.service.jobs.lock:self.service.jobs._start_next(None)
        return self.status()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=3)
