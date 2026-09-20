"""880823 only: mature TDX readers in an isolated dependency subprocess."""
from pathlib import Path
import json, os, subprocess, sys, tempfile

SYMBOL='TDX880823'


def read_source(start=None,end=None,tdx_directory=None,file_path=None):
    import pandas as pd
    if file_path and Path(file_path).suffix.lower() in {'.csv','.tsv','.txt','.parquet'}:
        path=Path(file_path)
        if path.suffix.lower()=='.parquet':frame=pd.read_parquet(path)
        else:
            try:frame=pd.read_csv(path,sep=None,engine='python',encoding='utf-8-sig')
            except UnicodeDecodeError:frame=pd.read_csv(path,sep=None,engine='python',encoding='gb18030')
        if 'symbol' in frame and not frame.symbol.astype(str).str.upper().isin([SYMBOL,'880823','SH880823']).all():
            raise ValueError('文件含其他标的，不能导入为通达信微盘股')
        return frame,'file/import'
    with tempfile.TemporaryDirectory() as folder:
        output=Path(folder)/'bars.parquet'
        request={'start':start,'end':end,'tdxDirectory':tdx_directory,'filePath':file_path,'output':str(output)}
        env={**os.environ,'PYTHONUTF8':'1','USERPROFILE':folder}
        deps=os.environ.get('V3_TDX_SITE') or str(Path(sys.prefix)/'tdx-site')
        script='import sys;sys.path.insert(0,sys.argv.pop(1));from v3_backend.research.tdx_quotes import child;child()'
        try:
            result=subprocess.run([sys.executable,'-c',script,deps,json.dumps(request)],stdin=subprocess.DEVNULL,
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40,env=env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:raise ValueError('通达信来源40秒未完成；可导入本机TDX数据或文件，已有缓存保留') from None
        if result.returncode or not output.exists():
            lines=[line.strip() for line in result.stderr.splitlines() if line.strip()]
            reason=lines[-1].removeprefix('ValueError: ')[:180] if lines else '来源没有返回日线'
            raise ValueError('通达信微盘股来源未连接或未返回880823数据；可导入本机TDX数据或CSV/Parquet。'+reason)
        return pd.read_parquet(output),'tdx/local' if tdx_directory or file_path else 'mootdx/tdx'


def child():
    import pandas as pd
    request=json.loads(sys.argv[1]);output=Path(request['output'])
    if request.get('tdxDirectory'):
        from mootdx.reader import Reader
        directory=Path(request['tdxDirectory'])
        if not (directory/'vipdoc/sh/lday/sh880823.day').is_file():raise ValueError('目录内没有vipdoc/sh/lday/sh880823.day')
        frame=Reader.factory(market='std',tdxdir=str(directory)).daily(symbol='880823')
    elif request.get('filePath'):
        path=Path(request['filePath'])
        if path.name.lower()!='sh880823.day':raise ValueError('请选择sh880823.day，以便原生读取器确认市场和价格单位')
        from mootdx.contrib.compat import MooTdxDailyBarReader
        frame=MooTdxDailyBarReader().get_df(str(path))
    else:
        from mootdx import config
        from mootdx.consts import HQ_HOSTS
        from mootdx.quotes import Quotes
        # Keep provider config local and use a few upstream hosts, no global IP scan.
        config.CONF=output.with_suffix('.config.json')
        config.CONF.write_text(json.dumps(config.settings),encoding='utf-8')
        frames=[];errors=[]
        for host in HQ_HOSTS[:3]:
            client=None
            try:
                client=Quotes.factory(market='std',server=tuple(host[1:]),bestip=False,timeout=3,auto_retry=False,raise_exception=True,heartbeat=False)
                for offset in range(0,16000,800):
                    part=client.index_bars(symbol='880823',frequency=9,start=offset,offset=800)
                    if part is None or part.empty:break
                    part=part.copy()
                    if 'datetime' in part:part['date']=pd.to_datetime(part.datetime)
                    else:part['date']=pd.to_datetime(part.index)
                    frames.append(part)
                    if not request.get('start') or str(part.date.min().date())<=request['start'] or len(part)<800:break
                if frames:break
            except Exception as exc:errors.append(type(exc).__name__)
            finally:
                if client is not None:client.close()
        if not frames:raise ValueError('TDX880823未返回行情：'+','.join(errors))
        frame=pd.concat(frames,ignore_index=True)
    if frame is None or frame.empty:raise ValueError('880823日线为空')
    frame=frame.copy()
    if 'date' not in frame:frame['date']=pd.to_datetime(frame['datetime'] if 'datetime' in frame else frame.index)
    frame=frame.rename(columns={'vol':'volume'})
    # Board-index volume is retained in source units, not relabelled as shares.
    frame.to_parquet(output,index=False)
