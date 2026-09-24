"""Validate the small set of application preferences with actual adapters."""
from copy import deepcopy

DATA_SOURCES = dict(daily='baostock', financials='baostock', boards='akshare',
                    intraday='akshare', microcap='tdx', quoteFallback=True)
CHOICES = dict(daily={'baostock','akshare','file'},financials={'baostock','file'},
               boards={'akshare','file'},intraday={'akshare','file'},microcap={'tdx','file'})


def source_settings(settings):
    value={**DATA_SOURCES,**settings.get('dataSources',{})}
    if 'daily' not in settings.get('dataSources',{}) and settings.get('defaultDataSource') in CHOICES['daily']:
        value['daily']=settings['defaultDataSource']
    return value


def validate(changes, current):
    result=deepcopy(changes)
    if any(key in result for key in ('_dataLocations','_dataMigrationId')):raise ValueError('数据迁移记录只能由迁移流程修改')
    if 'dataUpdates' in result:
        value=result['dataUpdates']
        if not isinstance(value,dict) or set(value)-{'enabled','watchlistIds','dailyPlanIds'}:raise ValueError('盘后更新设置格式无效')
        if 'enabled' in value and not isinstance(value['enabled'],bool):raise ValueError('盘后更新开关格式无效')
        for key in ('watchlistIds','dailyPlanIds'):
            if key in value and (not isinstance(value[key],list) or any(not isinstance(x,str) or not x for x in value[key])):raise ValueError('请选择有效的更新范围')
        result['dataUpdates']={**current.get('dataUpdates',{}),**value}
    if 'aiInstructions' in result and not isinstance(result['aiInstructions'],str):raise ValueError('AI偏好应为文字')
    if 'aiPurposes' in result:
        from .ai_settings import PURPOSES
        overrides=result['aiPurposes']
        if not isinstance(overrides,dict) or set(overrides)-PURPOSES:raise ValueError('AI用途设置格式无效')
        for value in overrides.values():
            if value is None:continue
            if not isinstance(value,dict) or set(value)-{'baseUrl','model','apiKey','temperature'}:raise ValueError('AI服务配置格式无效')
            if any(key in value and not isinstance(value[key],str) for key in ('baseUrl','model','apiKey')):raise ValueError('服务地址、模型和密钥须为文字')
            if 'temperature' in value:
                import math
                if isinstance(value['temperature'],bool) or not isinstance(value['temperature'],(int,float)) or not math.isfinite(value['temperature']) or not 0<=value['temperature']<=2:raise ValueError('模型温度须为0到2')
    if 'storage' in result:
        from pathlib import Path
        values=result['storage']
        if not isinstance(values,dict) or set(values)-{'dataDirectory','newProjectDirectory'}:raise ValueError('存储目录设置格式无效')
        normalized={**current.get('storage',{})}
        for key,path in values.items():
            if not isinstance(path,str) or not path.strip() or not Path(path).is_absolute():raise ValueError('请选择有效的绝对目录')
            folder=Path(path).resolve()
            if folder.exists() and not folder.is_dir():raise ValueError('所选位置不是目录')
            normalized[key]=str(folder)
        result['storage']=normalized
    if 'general' in result:
        value=result['general']
        if not isinstance(value,dict) or any(k not in {'checkUpdates'} or not isinstance(v,bool) for k,v in value.items()):
            raise ValueError('通用设置格式无效')
        result['general']={**current.get('general',{}),**value}
    if 'dataSources' in result:
        if not isinstance(result['dataSources'],dict):raise ValueError('数据源设置格式无效')
        unknown=set(result['dataSources'])-set(DATA_SOURCES)
        if unknown:raise ValueError('未知数据类别：'+','.join(sorted(unknown)))
        value={**source_settings(current),**result['dataSources']}
        for category,choices in CHOICES.items():
            if value[category] not in choices:raise ValueError('该数据类别尚未支持所选接口：'+category)
        if not isinstance(value['quoteFallback'],bool):raise ValueError('备用源设置应为开关')
        result['dataSources']=value
        result['defaultDataSource']=value['daily']
    elif 'defaultDataSource' in result:
        if result['defaultDataSource'] not in CHOICES['daily']:raise ValueError('未知日线数据源')
        result['dataSources']={**source_settings(current),'daily':result['defaultDataSource']}
    return result


def capabilities():
    return [dict(id='baostock',name='BaoStock 免费数据',categories=['daily','financials'],
                 description='沪深日线与公告财务；实际历史覆盖随来源变化。'),
            dict(id='akshare',name='AKShare 免费接口',categories=['daily','boards','intraday'],
                 description='日线、行业概念和分时分钟；分钟历史按来源实际范围。'),
            dict(id='tdx',name='通达信',categories=['microcap'],
                 description='当前接入微盘股880823及本机导入；不表示所有通达信数据可用。'),
            dict(id='file',name='已有数据与文件',categories=list(CHOICES),
                 description='仅使用已有或导入数据，缺失时提示，不自动联网补取。')]
