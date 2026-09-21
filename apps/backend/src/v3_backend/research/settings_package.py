"""Portable display/compute preferences, excluding accounts and research contents."""
from copy import deepcopy
import json
from pathlib import Path
from .storage import now
from .workbench import workspace
from .app_settings import validate

DISPLAY={'theme','density','sidebarWidth','aiWidth','sidebarVisible','aiVisible','rightPanel',
         'zoomFactor','readingFontSize','shortcuts','layoutPresets'}
APPLICATION={'compute','dataSources','general'}
LAYOUT={'sidebarVisible','aiVisible','sidebarWidth','aiWidth','density','rightPanel','layout'}


def clean(value):
    state={k:deepcopy(v) for k,v in value.get('workspace',{}).items() if k in DISPLAY and not isinstance(v,(dict,list))}
    original=value.get('workspace',{})
    if isinstance(original.get('navigation'),dict):
        known={'today','quote','market','screener','selection','positions','data','reports'}
        state['navigation']={key:[item for item in original['navigation'].get(key,[]) if isinstance(item,str) and item in known]
            for key in ('order','hidden','pinned') if isinstance(original['navigation'].get(key,[]),list)}
    if isinstance(original.get('layoutPresets'),dict):
        state['layoutPresets']={name:{k:v for k,v in preset.items() if k in LAYOUT and isinstance(v,(str,int,float,bool))}
            for name,preset in original['layoutPresets'].items() if isinstance(preset,dict)}
    if isinstance(original.get('shortcuts'),dict):
        state['shortcuts']={k:v for k,v in original['shortcuts'].items() if k in {'commandSearch','settings','sidebar','assistant','quoteList'} and isinstance(v,str)}
    settings={};incoming=value.get('settings',{})
    if isinstance(incoming.get('compute'),dict):
        settings['compute']={k:v for k,v in incoming['compute'].items() if k in {'profile','maxConcurrentJobs','threadsPerJob'} and isinstance(v,(str,int,float))}
    if isinstance(incoming.get('dataSources'),dict):
        from .app_settings import DATA_SOURCES
        settings['dataSources']={k:v for k,v in incoming['dataSources'].items() if k in DATA_SOURCES and isinstance(v,(str,bool))}
    if isinstance(incoming.get('general'),dict):
        settings['general']={k:v for k,v in incoming['general'].items() if k=='checkUpdates' and isinstance(v,bool)}
    return dict(workspace=state,settings=settings)


def package(store):
    state=workspace(store);settings=store.settings()
    return dict(format='v3-settings',version=1,createdAt=now(),**clean(dict(workspace=state,settings=settings)))


def load(params):
    value=params.get('package')
    if value is None:value=json.loads(Path(params['path']).read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict) or value.get('format')!='v3-settings' or value.get('version')!=1:
        raise ValueError('不是支持的V3设置包')
    return clean(value)


def dispatch(store,method,params):
    if method=='settings.export':return package(store)
    if method=='settings.importPreview':
        incoming=load(params);current=package(store)
        differences=[dict(section=section,key=key,current=current[section].get(key),incoming=value)
                     for section in incoming for key,value in incoming[section].items() if current[section].get(key)!=value]
        conflicts=[name for name in incoming['workspace'].get('layoutPresets',{}) if name in current['workspace'].get('layoutPresets',{})]
        return dict(package=dict(format='v3-settings',version=1,**incoming),differences=differences,layoutConflicts=conflicts)
    if method=='settings.import':
        incoming=load(params)
        mode=params.get('conflict')
        if mode not in {'keep','replace'}:raise ValueError('请选择同名布局保留本机还是使用导入版本')
        if mode=='keep':
            existing=workspace(store).get('layoutPresets',{})
            incoming['workspace']['layoutPresets']={k:v for k,v in incoming['workspace'].get('layoutPresets',{}).items() if k not in existing}
        settings=validate(incoming['settings'],store.settings())
        from .resources import compute_settings
        import os
        if 'compute' in settings:compute_settings(settings['compute'],os.cpu_count())
        state=workspace(store,incoming['workspace'],persist=False)
        store.settings(settings)
        store.put('workspace',dict(state,id='current'))
        return dict(imported=True,workspace=state)
    if method=='diagnostics.preview':
        # Deliberately summarize statuses rather than export paths, parameters,
        # tool messages, credentials or conversations.
        jobs=store.list('job');counts={}
        for job in jobs:counts[job['status']]=counts.get(job['status'],0)+1
        return dict(format='v3-diagnostics',createdAt=now(),projects=len(store.list('project')),
                    tasks=counts,settings=package(store),containsCredentials=False,containsResearchData=False)
    raise ValueError('未知设置包操作')
