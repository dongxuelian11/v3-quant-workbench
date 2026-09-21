import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from v3_backend.research import analysis_reader, table_reader, result_export


class ReadCancellation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'rows.parquet'
        pd.DataFrame({'date':pd.date_range('2000-01-01',periods=40000), 'symbol':['SH600000']*40000,
                      'value':range(40000)}).to_parquet(self.path,index=False,row_group_size=8192)
        self.event=threading.Event()
        self.store=SimpleNamespace(artifact_path=lambda *_:self.path)
        self.experiment={'id':'export','metrics':{},'artifacts':[{'type':'parquet','name':'rows','path':str(self.path)}]}

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        if self.event.is_set():raise InterruptedError('读取已取消')

    def test_cancel_running_scan_frees_two_thread_pool(self):
        for reader in ('analysis','table'):
            with self.subTest(reader=reader), ThreadPoolExecutor(max_workers=2) as pool:
                self.event.clear();started=threading.Event();release=threading.Event();calls=[]
                def check():
                    calls.append(1)
                    if len(calls)==4:
                        started.set()
                        if not release.wait(5):raise AssertionError('test release missing')
                    self.check()
                def run():
                    if reader=='analysis':return analysis_reader.read(self.path,'rows',{},check_cancel=check)
                    return table_reader.page(self.path,{'symbol':'SH600000'},'rows',check_cancel=check)
                future=pool.submit(run)
                try:
                    self.assertTrue(started.wait(5))
                    quick=pool.submit(table_reader.page,self.path,{'limit':2},'rows')
                    self.assertEqual(len(quick.result(timeout=5)['rows']),2)
                    self.event.set();release.set()
                    with self.assertRaises(InterruptedError):future.result(timeout=5)
                    self.assertEqual(pool.submit(lambda:'slot reused').result(timeout=5),'slot reused')
                finally:release.set()

    def test_pre_cancel_and_nested_calendar(self):
        self.event.set()
        with patch.object(table_reader.pq,'ParquetFile',side_effect=AssertionError('must not open')):
            for call in (lambda:table_reader.preview(self.path,2,check_cancel=self.check),
                         lambda:table_reader.calendar(self.path,check_cancel=self.check),
                         lambda:table_reader.replay_counts(self.path,check_cancel=self.check)):
                with self.assertRaises(InterruptedError):call()
        self.event.clear()
        def calendar(*args,**kwargs):
            self.event.set();kwargs['check_cancel']()
        with patch.object(analysis_reader,'calendar',side_effect=calendar):
            with self.assertRaises(InterruptedError):
                analysis_reader.read(self.path,'factor_IC',{'rolling':{'window':20}},self.path,check_cancel=self.check)

    def test_cancel_partial_csv_preserves_existing_export(self):
        final=self.root/'export.csv';final.write_bytes(b'previous export')
        original=pd.DataFrame.to_csv
        def write(frame,*args,**kwargs):
            result=original(frame,*args,**kwargs);self.event.set();return result
        with patch.object(pd.DataFrame,'to_csv',write):
            with self.assertRaises(InterruptedError):
                result_export.export(self.store,'p',self.experiment,self.root,'csv',check_cancel=self.check)
        self.assertEqual(final.read_bytes(),b'previous export')
        self.assertFalse(list(self.root.glob('*.writing.*')))

    def test_cancel_xlsx_removes_sheet_temporary_files(self):
        from openpyxl.worksheet._write_only import WriteOnlyWorksheet
        from openpyxl.worksheet._writer import ALL_TEMP_FILES
        before=set(ALL_TEMP_FILES);count=[0];original=WriteOnlyWorksheet.append
        def append(sheet,row):
            original(sheet,row);count[0]+=1
            if count[0]==260:self.event.set()
        with patch.object(WriteOnlyWorksheet,'append',append):
            with self.assertRaises(InterruptedError):
                result_export.export(self.store,'p',self.experiment,self.root,'xlsx',check_cancel=self.check)
        self.assertFalse((self.root/'export.xlsx').exists())
        self.assertFalse(list(self.root.glob('export-*.xlsx')))
        self.assertFalse(list(self.root.glob('*.writing.*')))
        self.assertEqual(set(ALL_TEMP_FILES),before)

    def test_cancellation_after_commit_does_not_retract_success(self):
        original=Path.replace
        def replace(path,target):
            result=original(path,target);self.event.set();return result
        with patch.object(Path,'replace',replace):
            result=result_export.export(self.store,'p',self.experiment,self.root,'csv',check_cancel=self.check)
        self.assertEqual(len(pd.read_csv(result['path'])),40000)

    def test_concurrent_tables_use_distinct_results_and_cancel_is_isolated(self):
        other=self.root/'other.parquet'
        pd.DataFrame({'value':[987]}).to_parquet(other,index=False)
        store=SimpleNamespace(artifact_path=lambda pid,a:Path(a['path']))
        experiment={**self.experiment,'artifacts':self.experiment['artifacts']+[{'type':'parquet','name':'other','path':str(other)}]}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(result_export.export,store,'p',experiment,self.root,'csv','rows')
            second=pool.submit(result_export.export,store,'p',experiment,self.root,'csv','other')
            a,b=first.result(timeout=5),second.result(timeout=5)
        self.assertNotEqual(a['path'],b['path'])
        self.assertEqual(len(pd.read_csv(a['path'])),40000)
        self.assertEqual(pd.read_csv(b['path']).value.tolist(),[987])
        prior={Path(a['path']),Path(b['path'])}
        original=pd.DataFrame.to_csv
        def write(frame,*args,**kwargs):
            result=original(frame,*args,**kwargs);self.event.set();return result
        with patch.object(pd.DataFrame,'to_csv',write):
            with self.assertRaises(InterruptedError):
                result_export.export(store,'p',experiment,self.root,'csv','rows',check_cancel=self.check)
        self.assertEqual(set(self.root.glob('*.csv')),prior)
        self.assertEqual(pd.read_csv(b['path']).value.tolist(),[987])
        self.assertFalse(list(self.root.glob('*.writing.*')))
