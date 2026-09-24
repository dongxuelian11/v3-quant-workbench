"""Local-file preview and explicit import choices; no network or preview writes."""
from pathlib import Path
from .storage import now,read_json,write_json

ALIASES={'code':'symbol','instrument':'symbol','日期':'date','股票代码':'symbol','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume','成交额':'amount','pubDate':'announcementDate','statDate':'reportDate'}
DATASETS={'auto','prices','financials','corporate_actions','benchmark_weights','flow','fund_flow','chips','lhb','industry','membership'}


def input_files(params):
    files=params.get('files',[])
    if not isinstance(files,list) or not files or any(not isinstance(file,str) or not file.strip() for file in files):raise ValueError('请选择 CSV/Excel/Parquet 文件')
    overrides=params.get('fileOptions',[])
    if not isinstance(overrides,list) or any(not isinstance(item,dict) or not isinstance(item.get('file'),str) for item in overrides):raise ValueError('逐文件选项必须包含文件路径')
    if len({item['file'] for item in overrides})!=len(overrides):raise ValueError('同一文件的导入选项不能重复')
    return files


def options(params,file):
    value=dict(params)
    for item in params.get('fileOptions',[]):
        if item.get('file')==file:value.update({k:v for k,v in item.items() if k!='file'})
    return value


def policy(params, *, writing=False):
    value=params.get('conflictPolicy','fill_missing')
    if value not in {'fill_missing','replace'}:raise ValueError('冲突处理仅支持补缺或替换')
    if writing and value=='replace' and params.get('replaceConfirmed') is not True:
        raise ValueError('替换冲突前必须明确确认；默认只补缺')
    return value


def validate_price_groups(prior,incoming,conflict_policy):
    """Never attach a new declaration to retained values or retain metadata on unknown input."""
    import pandas as pd
    if prior is None or prior.empty:return
    keys=['symbol','date']
    old=prior.set_index(keys);new=incoming.set_index(keys)
    common=old.index.intersection(new.index)
    old=old.reindex(common);new=new.reindex(common)
    groups=[(['volume'],'volumeUnit','成交量单位'),(['amount'],'amountUnit','成交额单位'),
        (['open','high','low','close','factor','preclose','rawOpen','rawHigh','rawLow','rawClose','rawPreclose'],'priceBasis','价格与复权口径')]
    for fields,label,title in groups:
        before=old.reindex(columns=fields);after=new.reindex(columns=fields)
        old_label=old[label] if label in old else pd.Series('unknown',index=common)
        new_label=new[label] if label in new else pd.Series('unknown',index=common)
        old_label=old_label.fillna('unknown').replace('','unknown');new_label=new_label.fillna('unknown').replace('','unknown')
        declared=new[label].notna() if label in new else pd.Series(False,index=common)
        participates=(before.notna().any(axis=1) & (after.notna().any(axis=1) | declared)) | (after.notna().any(axis=1) & old_label.ne('unknown'))
        if (participates & old_label.ne(new_label)).any():
            raise ValueError(title+'不一致或一方未知；不能拼接数值与口径，请核对来源后使用一致声明重新导入')
        if label!='priceBasis':continue
        changed=after.notna() & (before.isna() | ~before.eq(after).fillna(False))
        applied=changed if conflict_policy=='replace' else after.notna() & before.isna()
        retained=before.notna() & (after.isna() if conflict_policy=='replace' else True)
        if (applied.any(axis=1) & retained.any(axis=1)).any():
            raise ValueError('价格与复权因子必须来自完整的一组输入；不能保留旧价格或因子再拼入新值')


def merge_frames(prior,incoming,keys,conflict_policy='fill_missing',provided_columns=None):
    """Update supplied cells only; missing input never destroys an existing value."""
    import pandas as pd
    if prior is None or prior.empty:prior=incoming.iloc[:0].copy()
    old=prior.drop_duplicates(keys,keep='last').set_index(keys)
    new=incoming.drop_duplicates(keys,keep='last').set_index(keys)
    columns=[c for c in new.columns if provided_columns is None or c in provided_columns]
    common=new.index.intersection(old.index)
    added=new.index.difference(old.index)
    old=old.reindex(columns=list(dict.fromkeys([*old.columns,*new.columns])))
    existing=old.reindex(common);received=new.reindex(common)
    conflicts=pd.DataFrame(False,index=common,columns=columns)
    filled=0;replaced=set()
    for column in columns:
        before=existing[column];after=received[column]
        supplied=after.notna();missing=before.isna()
        different=supplied & ~missing & ~before.eq(after).fillna(False)
        conflicts[column]=different
        filled+=int((supplied & missing).sum())
        chosen=supplied & (missing | (conflict_policy=='replace'))
        if chosen.any():
            if old[column].dtype!=after.dtype:old[column]=old[column].astype(object)
            old.loc[common[chosen],column]=after[chosen]
        if conflict_policy=='replace':replaced.update(common[different].tolist())
    merged=pd.concat([old,new.loc[added]],axis=0).reset_index()
    return merged,dict(newRows=len(added),existingRows=len(common),conflictRows=int(conflicts.any(axis=1).sum()),fillableCells=filled,filledCells=filled,replacedRows=len(replaced))


def _read(file,params,metadata=None):
    import pandas as pd
    path=Path(file)
    mapping=params.get('mapping',params.get('fieldMapping',{}))
    if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):raise ValueError('字段映射必须为原列名到目标列名')
    strings={'symbol':str,'code':str,'instrument':str,'股票代码':str,**{k:str for k,v in mapping.items() if ALIASES.get(v,v)=='symbol'}}
    if path.suffix.lower()=='.csv':frame=pd.read_csv(path,dtype=strings)
    elif path.suffix.lower()=='.parquet':frame=pd.read_parquet(path)
    elif path.suffix.lower() in {'.xlsx','.xls'}:frame=pd.read_excel(path,dtype=strings)
    else:raise ValueError('只支持 CSV/Excel/Parquet')
    original=[str(c) for c in frame.columns]
    if metadata is not None:
        from .data import records
        metadata.update(rows=len(frame),columns=[dict(source=c,target=mapping.get(c,c)) for c in original],sample=records(frame.head(5)))
    frame=frame.rename(columns=mapping)
    if frame.columns.duplicated().any():raise ValueError('字段映射后列名重复，请调整映射')
    return frame,dict(zip(original,frame.columns))


def _kind(frame,params):
    selected=params.get('dataset',params.get('kind','auto'))
    if selected not in DATASETS:raise ValueError('不支持此导入数据类型')
    if selected!='auto':return 'fund_flow' if selected=='flow' else selected
    columns=set(frame.columns)
    if {'cashPerShare','bonusRatio','exDate'}<=columns:return 'corporate_actions'
    if {'benchmark','weight','effectiveDate','symbol'}<=columns:return 'benchmark_weights'
    if {'industry','symbol'}<=columns and ('effectiveDate' in columns or 'startDate' in columns):return 'industry'
    if {'symbol','startDate','endDate'}<=columns:return 'membership'
    return 'prices' if {'date','open','close','high','low','volume'}<=set(frame.rename(columns=ALIASES).columns) else 'financials'


def prepare(project,file,params,read_metadata=None):
    import pandas as pd
    from . import data
    frame,mapping=_read(file,params,read_metadata);kind=_kind(frame,params)
    if not isinstance(params.get('units',{}),dict):raise ValueError('单位选择必须是对象')
    if set(params.get('units',{}))-{'volume','amount'}:raise ValueError('单位选择仅支持volume和amount')
    units={**{'volume':'unknown','amount':'unknown'},**params.get('units',{})}
    if units['volume'] not in {'unknown','shares','lots'} or units['amount'] not in {'unknown','CNY','ten_thousand_CNY'}:
        raise ValueError('成交量单位仅支持unknown/shares/lots，金额仅支持unknown/CNY/ten_thousand_CNY')
    basis=params.get('priceBasis','unknown')
    if basis not in {'unknown','unadjusted','forward_adjusted','backward_adjusted'}:raise ValueError('复权口径无效')
    warnings=[];provided=list(frame.columns);prior=None;keys=[]
    if kind in {'prices','financials'}:
        frame=frame.rename(columns=ALIASES)
        if frame.columns.duplicated().any():raise ValueError('标准字段重复，请调整映射')
        mapping={k:ALIASES.get(v,v) for k,v in mapping.items()}
        if kind=='prices':
            for field,scales,unit_field,target in [('volume',{'shares':1,'lots':100},'volumeUnit','shares'),('amount',{'CNY':1,'ten_thousand_CNY':10000},'amountUnit','CNY')]:
                unit=units[field]
                if unit=='unknown':warnings.append(('成交量' if field=='volume' else '成交额')+'单位未知，保持原值，不自动换算')
                elif field in frame:
                    frame[field]=pd.to_numeric(frame[field],errors='raise')*scales[unit]
                    frame[unit_field]=target
            if basis=='unknown':warnings.append('复权口径未知；不根据价格或factor列猜测，也不自动复权')
            else:frame['priceBasis']=basis
        elif any(value!='unknown' for value in units.values()):warnings.append('财务各指标单位由字段来源决定；成交量/成交额单位选项不转换财务指标')
        provided=list(frame.columns)
        frame,kind=data.normalize(frame,kind)
        keys=['symbol','date'] if kind=='prices' else ['symbol','reportDate','announcementDate']
        root=Path(data.project_data(project)['path'])/'data'
        if (root/(kind+'.parquet')).exists() or (root/kind).exists():prior=data.read_table(project,kind,symbols=frame.symbol.unique() if kind=='prices' else None)
    elif kind in {'fund_flow','chips','lhb'}:
        from .alternative_data import normalize
        frame=normalize(frame,kind)
    elif kind=='corporate_actions':
        from .corporate_actions import validate
        frame=validate(frame)
    elif kind=='benchmark_weights':
        from .benchmarks import validate_weights
        frame=validate_weights(frame)
    elif kind=='industry':
        frame=frame.rename(columns={'startDate':'effectiveDate'})
        if not {'symbol','industry','effectiveDate'}.issubset(frame):raise ValueError('历史行业需要 symbol/industry/effectiveDate')
        frame=frame[['symbol','industry','effectiveDate']].copy();frame['symbol']=frame.symbol.map(data.symbol)
        frame['effectiveDate']=pd.to_datetime(frame.effectiveDate,errors='raise').dt.strftime('%Y-%m-%d')
        if frame.isna().any().any():raise ValueError('行业或生效日期缺失')
    elif kind=='membership':
        if not {'symbol','startDate','endDate'}.issubset(frame):raise ValueError('历史成员需要 symbol/startDate/endDate 列')
        frame=frame.copy();frame['symbol']=frame.symbol.map(data.symbol)
        for key in ('startDate','endDate'):frame[key]=pd.to_datetime(frame[key],errors='raise')
        if frame.startDate.isna().any() or (frame.endDate<frame.startDate).any():raise ValueError('成员生效区间无效')
        warnings.append('成员导入保存新版本并返回版本引用，历史版本保留；不改写旧成员记录')
    if kind not in {'prices','financials','membership'}:
        warnings.append('此类型目前仅支持明确确认后使用原适配器替换；不支持补缺，选择补缺时会拒绝该文件')
    row=dict(file=str(file),fileName=Path(file).name,status='ready',kind=kind,rows=len(frame),columns=[dict(source=k,target=v) for k,v in mapping.items()],sample=data.records(frame.head(5)),units=units,outputUnits=dict(volume='shares' if kind=='prices' and units['volume']!='unknown' else 'unknown',amount='CNY' if kind=='prices' and units['amount']!='unknown' else 'unknown'),priceBasis=basis,warnings=warnings,
        supportedConflictPolicies=['fill_missing','replace'] if kind in {'prices','financials','membership'} else ['replace'])
    if kind=='prices':validate_price_groups(prior,frame,policy(params))
    if keys:row['merge']=merge_frames(prior,frame,keys,policy(params),provided)[1]
    row['conflictPolicySupported']=policy(params) in row['supportedConflictPolicies']
    if not row['conflictPolicySupported']:row.update(status='failed',message='此数据类型暂不支持补缺；请明确选择并确认替换，或取消该文件')
    return frame,row,provided


def error_message(exc):
    if isinstance(exc,FileNotFoundError):return '文件不存在，请重新选择文件'
    if isinstance(exc,PermissionError):return '无法读取或写入文件，请检查占用和访问权限'
    if isinstance(exc,(ValueError,TypeError)):
        text=str(exc)
        if not any(mark in text for mark in ('Traceback','\\',':/','/Users/','/home/')):return text[:300]
    return '文件读取或校验失败，请检查格式、字段和数据内容'


def preview(project,params):
    rows=[]
    for file in input_files(params):
        metadata={}
        try:rows.append(prepare(project,file,options(params,file),read_metadata=metadata)[1])
        except Exception as exc:rows.append(dict(file=str(file),fileName=Path(file).name,status='failed',message=error_message(exc),warnings=[],**metadata))
    return dict(files=rows,warnings=['预览不写入数据；实际导入时会重新读取并校验文件和冲突。'])


def import_files(project,params,progress):
    from . import data
    files=input_files(params)
    summaries=[]
    for index,file in enumerate(files):
        item=dict(file=str(file),fileName=Path(file).name)
        write_started=False
        try:
            selected=options(params,file);choice=policy(selected,writing=True)
            frame,preview_row,provided=prepare(project,file,selected);item.update(preview_row)
            if preview_row['status']=='failed':raise ValueError(preview_row['message'])
            kind=preview_row['kind']
            write_started=True
            if kind in {'prices','financials'}:
                saved=data.merge_table(project,frame,kind,conflict_policy=choice,provided_columns=provided)
                item.update(preview_row['merge'],totalRows=len(saved))
            elif kind=='corporate_actions':
                from .corporate_actions import import_frame
                item['totalRows']=import_frame(project,frame)['rows']
            elif kind=='benchmark_weights':
                from .benchmarks import import_weights
                item['totalRows']=import_weights(project,frame)
            elif kind in {'fund_flow','chips','lhb'}:
                from .alternative_data import import_frame
                item['result']=import_frame(project,kind,frame)
            elif kind=='industry':
                from .history import import_industry
                item['totalRows']=import_industry(project,frame)
            else:
                from .history import import_membership
                item['totalRows']=import_membership(project,frame,selected.get('poolId'),str(selected.get('membershipSource','import')))
                item['membershipRef']=dict(project['universe']['membershipRef'])
            item.update(status='completed',importedRows=len(frame),message='已导入；冲突保留原值' if choice=='fill_missing' and item.get('conflictRows') else '已导入')
        except Exception as exc:
            message=error_message(exc)
            if write_started:message+='；可能已有部分分区写入；按原设置重试会重新校验'
            item.update(status='failed',message=message)
        summaries.append(item)
        progress((index+1)/len(files)*.9,('已导入 ' if item['status']=='completed' else '导入失败 ')+Path(file).name)
    completed=sum(item['status']=='completed' for item in summaries)
    warnings=['复权与单位按文件声明处理；未知值保持未知。财务按公告日之后交易日生效。']
    metadata_status='not_written'
    if completed:
        source=Path(data.project_data(project)['path'])/'data/source.json'
        try:
            old=read_json(source,{})
            write_json(source,{**old,'source':'import','updatedAt':now(),'imports':summaries,'warnings':list(dict.fromkeys(old.get('warnings',[])+warnings))})
            metadata_status='completed'
        except Exception as exc:
            metadata_status='failed'
            warnings.append('数据文件已写入，但来源说明保存失败；无需重新导入成功文件：'+error_message(exc))
    return dict(imports=summaries,warnings=warnings,metadataStatus=metadata_status,status='completed' if completed==len(files) else 'partial' if completed else 'failed',completedFiles=completed,failedFiles=[item['file'] for item in summaries if item['status']=='failed'])
