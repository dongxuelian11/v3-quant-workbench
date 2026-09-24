"""Opt-in post-close data jobs on the existing running-app scheduler."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .storage import now


def tick(service, clock=None):
    if getattr(service,'migrations',None) and service.migrations.pause.is_set():return
    store=service.store;config=store.settings().get('dataUpdates',{})
    if not config.get('enabled'):return
    clock=clock or datetime.now(ZoneInfo('Asia/Shanghai'))
    if clock.weekday()>4 or clock.hour<16:return
    today=clock.date().isoformat()
    scopes=[('watchlist',key) for key in config.get('watchlistIds',[])]+[('daily_plan',key) for key in config.get('dailyPlanIds',[])]
    for kind,key in scopes:
        token=today+'-'+kind+'-'+key
        try:store.get('scheduled_update',token);continue
        except ValueError:pass
        # Recover submit-before-status persistence without submitting a second job.
        existing=next((j for j in store.list('job') if j.get('spec',{}).get('parameters',{}).get('scheduledUpdateId')==token),None)
        if existing:
            store.put('scheduled_update',dict(id=token,jobId=existing['id'],createdAt=now()));continue
        try:
            value=store.get(kind,key)
            if kind=='watchlist':
                if not value.get('symbols'):continue
                project=store.project(None)
                project['universe']={**project['universe'],'source':'manual','symbols':deepcopy(value['symbols'])}
            else:
                if not value.get('enabled'):continue
                from .screeners import freeze_run
                plan=deepcopy(value['planSnapshot']);project=freeze_run(store,plan)
            # Incremental adapter reuses prior data; this is preparation only, never selection.
            spec=dict(kind='data.update',name='盘后数据更新 · '+value.get('name',key),
                parameters=dict(startDate=(clock.date()-timedelta(days=400)).isoformat(),endDate=today,
                    financials=False,corporateActions=False,scheduledUpdateId=token))
            if project.get('id'):spec['projectId']=project['id']
            job=service.jobs.submit(spec,frozen_project=project)
            store.put('scheduled_update',dict(id=token,jobId=job['id'],createdAt=now()))
        except Exception as exc:
            store.put('scheduled_update',dict(id=token,status='failed',message=str(exc),createdAt=now()))
            service.emit(dict(kind='data.update.notice',status='failed',message='盘后数据准备失败：'+str(exc)))
