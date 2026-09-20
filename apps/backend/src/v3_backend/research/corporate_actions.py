"""Explicit entitlement events, independent of price adjustment factors."""
from copy import deepcopy
import math
from pathlib import Path
import pandas as pd


def validate(frame):
    """Canonical per-share cash and bonus ratios; actual dates, not proposals.

    cashPerShare is the declared cash amount under the explicit taxBasis.
    Unavailable payment/listing dates remain unresolved, never inferred.
    """
    frame=frame.copy()
    required={'id','symbol','announcementDate','recordDate','exDate','cashPerShare','bonusRatio','status'}
    if not required.issubset(frame):raise ValueError('公司行动缺少列: '+', '.join(sorted(required-set(frame))))
    from .data import symbol
    frame['symbol']=frame.symbol.map(symbol)
    if frame.id.isna().any():raise ValueError('公司行动 id 不能为空')
    frame['id']=frame.id.astype(str).str.strip()
    if frame.id.eq('').any():raise ValueError('公司行动 id 不能为空')
    if frame.id.duplicated().any():raise ValueError('公司行动 id 重复')
    for key in ('announcementDate','recordDate','exDate','payDate','listingDate'):
        if key not in frame:frame[key]=None
        parsed=pd.to_datetime(frame[key],errors='raise')
        frame[key]=parsed.dt.strftime('%Y-%m-%d').where(parsed.notna(),None)
    for key in ('cashPerShare','bonusRatio'):
        frame[key]=pd.to_numeric(frame[key],errors='raise')
        if not frame[key].map(lambda x:math.isfinite(x) and x>=0).all():raise ValueError(key+' 必须非负且已知')
    if 'taxBasis' not in frame:frame['taxBasis']=None
    implemented=frame.status.eq('implemented')
    if frame.loc[implemented].duplicated(['symbol','exDate']).any():
        raise ValueError('同证券除权日有多条已实施记录，请按同一行动id修订或合并明确的分配，不能重复派息')
    if frame.loc[implemented,['announcementDate','recordDate','exDate']].isna().any(axis=None):
        raise ValueError('已实施公司行动须提供公告、登记和除权日期')
    for row in frame.loc[implemented].to_dict('records'):
        if not row['announcementDate']<=row['recordDate']<row['exDate']:
            raise ValueError('公司行动公告/登记/除权日期顺序无效: '+str(row['id']))
        if any(row.get(k) and row[k]<row['exDate'] for k in ('payDate','listingDate')):
            raise ValueError('派息或红股上市日期不能早于除权日: '+str(row['id']))
    return frame


def read(project):
    from .data import project_data
    path=Path(project_data(project)['path'])/'data'/'corporate_actions.parquet'
    return validate(pd.read_parquet(path)) if path.exists() else pd.DataFrame()


def import_frame(project, frame):
    from .data import project_data
    path=Path(project_data(project)['path'])/'data'/'corporate_actions.parquet'
    new=validate(frame)
    old=read(project)
    # Preserve announced revisions as distinct ids supplied by the importer.
    merged=pd.concat([old,new],ignore_index=True).drop_duplicates('id',keep='last')
    merged=validate(merged)
    path.parent.mkdir(parents=True,exist_ok=True)
    revisions=path.with_name('corporate_actions_history.parquet')
    history=pd.read_parquet(revisions) if revisions.exists() else pd.DataFrame()
    from .storage import now
    history=pd.concat([history,new.assign(importedAt=now())],ignore_index=True)
    history.to_parquet(revisions.with_suffix('.tmp.parquet'),index=False)
    revisions.with_suffix('.tmp.parquet').replace(revisions)
    temporary=path.with_suffix('.tmp.parquet')
    merged.to_parquet(temporary,index=False)
    temporary.replace(path)
    return {'rows':len(merged),'path':str(path)}


def from_baostock(frame):
    """Retain gross cash; the source's alternative after-tax strings are not a tax rule."""
    from .data import symbol
    rows=[]
    for source in frame.to_dict('records'):
        ex=source.get('dividOperateDate');announcement=source.get('dividPlanDate')
        if not ex or not announcement:continue  # A proposal is not an implemented entitlement.
        text=source.get('dividCashStock','')
        bonus=source.get('dividStocksPs')
        reserve=source.get('dividReserveToStockPs')
        if not reserve and '转' not in text:reserve=0
        if not bonus and '送' not in text:bonus=0
        if reserve in ('',None) or bonus in ('',None):raise ValueError('公司行动送转比例不明确')
        code=symbol(source['code'])
        rows.append(dict(id=f'{code}:{ex}:{announcement}',symbol=code,announcementDate=announcement,
            recordDate=source.get('dividRegistDate') or None,exDate=ex,payDate=source.get('dividPayDate') or None,
            listingDate=source.get('dividStockMarketDate') or None,cashPerShare=float(source['dividCashPsBeforeTax']),
            bonusRatio=float(bonus)+float(reserve),status='implemented',taxBasis='gross_cash_before_tax_assumption',
            source='baostock',sourceDescription=text,sourceAfterTax=source.get('dividCashPsAfterTax')))
    return validate(pd.DataFrame(rows)) if rows else pd.DataFrame()


def collect(project, bs, codes, start, end, query, progress=lambda *_:None):
    """Checkpoint each completed symbol using the existing data job process."""
    count=0
    for index,code in enumerate(codes):
        frames=[]
        for year in range(pd.Timestamp(start).year,pd.Timestamp(end).year+1):
            frame=query(bs,bs.query_dividend_data,code[:2].lower()+'.'+code[2:],year=str(year),yearType='operate')
            if not frame.empty:frames.append(frame)
        if frames:
            canonical=from_baostock(pd.concat(frames,ignore_index=True))
            if not canonical.empty:
                canonical=canonical[canonical.exDate.between(str(start)[:10],str(end)[:10])]
                if not canonical.empty:import_frame(project,canonical);count+=len(canonical)
        progress((index+1)/max(1,len(codes)),f'公司行动 {code}')
    return {'rows':count,'source':'baostock','taxBasis':'gross_cash_before_tax_assumption'}


def apply(account, date, actions, phase='open'):
    """Return copied account and events; registration occurs AFTER close trades."""
    account=deepcopy(account);day=str(date)[:10];events=[]
    if len(actions):actions=validate(pd.DataFrame(actions))
    entitlements=account.setdefault('entitlements',{})
    done=account.setdefault('processedActions',[])
    for row in actions.to_dict('records') if isinstance(actions,pd.DataFrame) else actions:
        if row.get('status')!='implemented' or str(row['announcementDate'])[:10]>day:continue
        code=row['symbol'];key=str(row['id'])
        if phase=='close' and row['recordDate']==day and key not in entitlements:
            shares=account['holdings'].get(code,{}).get('quantity',0)
            entitlements[key]={'symbol':code,'quantity':shares,'cash':shares*row['cashPerShare'],'shares':shares*row['bonusRatio'],
                'cashPerShare':row['cashPerShare'],'bonusRatio':row['bonusRatio'],'recordDate':row['recordDate'],'exDate':row['exDate']}
            events.append(dict(date=day,symbol=code,actionId=key,kind='record',quantity=shares))
        entitlement=entitlements.get(key)
        if entitlement and any(field in entitlement and entitlement[field]!=row[field] for field in ('cashPerShare','bonusRatio','recordDate','exDate')):
            raise ValueError('公司行动修订与已登记权益不一致，需核对原始权益后续算: '+key)
        if phase=='open' and row['exDate']==day and entitlement is None and account['holdings'].get(code,{}).get('quantity',0):
            raise ValueError('持仓缺登记日权益快照: '+key)
        if not entitlement or phase!='open':continue
        for kind,field in [('ex','exDate'),('pay','payDate'),('listing','listingDate')]:
            marker=key+':'+kind
            if row.get(field)!=day or marker in done:continue
            if kind=='ex':
                account['receivables']=account.get('receivables',0)+entitlement['cash']
                account['pendingShares']=account.get('pendingShares',0)+entitlement['shares']
                h=account['holdings'].setdefault(code,dict(quantity=0,sellableQuantity=0,costPrice=0))
                h['pendingQuantity']=h.get('pendingQuantity',0)+entitlement['shares']
                # Allocate the existing acquisition basis across old and bonus shares now,
                # so a sale before listing does not discard the bonus shares' basis.
                total=h['quantity']+h['pendingQuantity']
                if entitlement['shares'] and total:
                    h['costPrice']=h.get('costPrice',0)*(total-entitlement['shares'])/total
            elif kind=='pay':
                if key+':ex' not in done:raise ValueError('分红到账缺除权应收记录: '+key)
                if entitlement['cash'] and not row.get('taxBasis'):raise ValueError('现金分红缺税额口径: '+key)
                account['cash']+=entitlement['cash'];account['receivables']-=entitlement['cash']
            else:
                if key+':ex' not in done:raise ValueError('红股上市缺除权权益记录: '+key)
                shares=entitlement['shares']
                if not float(shares).is_integer():raise ValueError('送转零碎股缺实际分配数量: '+key)
                h=account['holdings'].setdefault(code,dict(quantity=0,sellableQuantity=0,costPrice=0))
                h['quantity']+=int(shares);h['sellableQuantity']+=int(shares)
                h['pendingQuantity']=h.get('pendingQuantity',0)-shares
                account['pendingShares']-=shares
            done.append(marker)
            events.append(dict(date=day,symbol=code,actionId=key,kind=kind,cash=entitlement['cash'] if kind=='pay' else 0,quantity=entitlement['shares'] if kind=='listing' else 0,taxBasis=row.get('taxBasis')))
    return account,events
