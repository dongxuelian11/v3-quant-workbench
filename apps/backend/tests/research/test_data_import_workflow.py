import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import data,data_imports,worker
from v3_backend.research.server import Service
from v3_backend.research.storage import read_json,write_json

class ImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'app')
        self.service.report_tasks.stop.set();self.service.report_tasks.thread.join(timeout=2)
        self.project=self.service.store.create_project(self.root/'project','import')
        self.pid=self.project['id']
        self.project['settings']['dataPath']=str(self.root/'project/data');self.service.store.save_project(self.project)
    def tearDown(self):self.service.close();self.temp.cleanup()
    def file(self,name,rows):
        path=self.root/name;pd.DataFrame(rows).to_csv(path,index=False);return str(path)
    def price(self,**changes):
        return dict(symbol='SH600000',date='2025-01-02',open=10.,high=12.,low=9.,close=10.,volume=100.,**changes)
    def import_(self,files,**params):return data.import_files(self.project,dict(files=files,**params),lambda *_:None)
    def preview(self,files,**params):return self.service.request('data.import.preview',dict(projectId=self.pid,files=files,**params))
    def snapshot(self):return {str(p.relative_to(self.root/'project')):p.read_bytes() for p in (self.root/'project').rglob('*') if p.is_file()}

    def test_readonly_preview_default_conflict_preserved_and_explicit_replace(self):
        original=self.file('original.csv',[self.price(amount=None,extra=42.)]);self.assertEqual(self.import_([original])['status'],'completed')
        incoming=self.price(amount=500.);incoming['close']=11.
        patch_file=self.file('new.csv',[incoming])
        before=self.snapshot();preview=self.preview([patch_file])['files'][0]
        self.assertEqual(self.snapshot(),before);self.assertEqual(preview['merge']['conflictRows'],1);self.assertEqual(preview['merge']['fillableCells'],1)
        result=self.import_([patch_file]);self.assertEqual(result['imports'][0]['conflictRows'],1)
        saved=data.read_table(self.project).iloc[0]
        self.assertEqual(saved.close,10.);self.assertEqual(saved.amount,500.);self.assertEqual(saved.extra,42.)
        denied=self.import_([patch_file],conflictPolicy='replace');self.assertEqual(denied['status'],'failed')
        self.assertEqual(data.read_table(self.project).iloc[0].close,10.)
        changed=self.import_([patch_file],conflictPolicy='replace',replaceConfirmed=True)
        self.assertEqual(changed['imports'][0]['replacedRows'],1)
        saved=data.read_table(self.project).iloc[0];self.assertEqual(saved.close,11.);self.assertEqual(saved.extra,42.)

    def test_units_unknown_preserved_and_explicit_conversion_matches_preview(self):
        source=self.file('lots.csv',[self.price(amount=2.)])
        preview=self.preview([source])['files'][0]
        self.assertEqual(preview['units'],dict(volume='unknown',amount='unknown'));self.assertEqual(preview['priceBasis'],'unknown')
        self.assertEqual(preview['sample'][0]['volume'],100.)
        self.import_([source]);self.assertEqual(data.read_table(self.project).iloc[0].volume,100.)
        source=self.file('explicit-lots.csv',[{**self.price(amount=2.),'date':'2025-01-03'}])
        params=dict(units=dict(volume='lots',amount='ten_thousand_CNY'),priceBasis='unadjusted',conflictPolicy='replace',replaceConfirmed=True)
        preview=self.preview([source],**params)['files'][0]
        self.assertEqual(preview['sample'][0]['volume'],10000.);self.assertEqual(preview['sample'][0]['amount'],20000.)
        self.import_([source],**params);saved=data.read_table(self.project).iloc[-1]
        self.assertEqual(saved.volume,10000.);self.assertEqual(saved.amount,20000.);self.assertEqual(saved.priceBasis,'unadjusted')

    def test_financial_cells_missing_columns_and_nulls_never_erase_existing_values(self):
        base=dict(symbol='SH600000',reportDate='2024-12-31',announcementDate='2025-03-01')
        self.import_([self.file('old-fin.csv',[dict(base,roe=10.,profit=None,assets=100.)])])
        new=self.file('new-fin.csv',[dict(base,roe=11.,profit=3.)])
        self.import_([new]);saved=data.read_table(self.project,'financials').iloc[0]
        self.assertEqual(saved.roe,10.);self.assertEqual(saved.profit,3.)
        blank=self.file('blank-fin.csv',[dict(base,roe=12.,profit=None)])
        self.import_([blank],conflictPolicy='replace',replaceConfirmed=True);saved=data.read_table(self.project,'financials').iloc[0]
        self.assertEqual(saved.roe,12.);self.assertEqual(saved.profit,3.);self.assertEqual(saved.assets,100.)

    def test_mixed_files_retry_only_failure_and_keep_success(self):
        good=self.file('good.csv',[self.price()]);bad=self.file('bad.csv',[dict(symbol='SH600000',date='broken')])
        result=self.import_([good,bad]);self.assertEqual(result['status'],'partial');self.assertEqual(result['failedFiles'],[bad])
        original=data.read_table(self.project).copy()
        self.file('bad.csv',[{**self.price(),'date':'2025-01-03','close':11.}])
        retried=self.import_(result['failedFiles']);self.assertEqual(retried['status'],'completed')
        saved=data.read_table(self.project);self.assertEqual(len(saved),2)
        pd.testing.assert_frame_equal(saved[saved.date.eq(pd.Timestamp('2025-01-02'))].reset_index(drop=True),original.reset_index(drop=True))

    def test_unsupported_fill_is_explicit_and_existing_types_remain_available(self):
        source=self.file('weights.csv',[dict(benchmark='csi300',symbol='SH600000',effectiveDate='2025-01-02',weight=1.)])
        row=self.preview([source],dataset='benchmark_weights')['files'][0]
        self.assertFalse(row['conflictPolicySupported']);self.assertEqual(row['supportedConflictPolicies'],['replace'])
        self.assertEqual(self.import_([source],dataset='benchmark_weights')['status'],'failed')
        self.assertFalse((self.root/'project/data/benchmark_weights.parquet').exists())
        result=self.import_([source],dataset='benchmark_weights',conflictPolicy='replace',replaceConfirmed=True)
        self.assertEqual(result['status'],'completed')
        invalid=self.file('incomplete.csv',[dict(benchmark='csi300',symbol='SH600000',effectiveDate='2025-01-02',weight=.5)])
        self.assertEqual(self.preview([invalid],dataset='benchmark_weights',conflictPolicy='replace')['files'][0]['status'],'failed')
        self.assertEqual(pd.read_parquet(self.root/'project/data/benchmark_weights.parquet').weight.tolist(),[1.])

    def test_worker_persists_partial_details_and_registers_failed_job_with_result(self):
        good=self.file('good.csv',[self.price()]);bad=str(self.root/'missing.csv')
        spec=dict(kind='data.import',projectId=self.pid,name='mixed import',parameters=dict(files=[good,bad]))
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(spec)
        directory=self.root/'project/.research/runs'/job['id'];directory.mkdir(parents=True)
        write_json(directory/'request.json',dict(appData=str(self.service.store.root),job=job))
        self.assertEqual(worker.run(directory),1)
        result=read_json(directory/'result.json');self.assertEqual(result['runtimeStatus'],'failed')
        details=read_json(directory/'details.json');self.assertEqual(details['status'],'partial');self.assertEqual(details['failedFiles'],[bad])
        write_json(directory/'process-exit.json',dict(cleanupConfirmed=True,returncode=1))
        recovered=self.service.jobs.recover_result(job['id'])
        self.assertEqual(recovered['status'],'failed');self.assertEqual(self.service.store.get('job',job['id'])['experimentId'],job['id'])
        self.assertIn('成功 1',result['experiment']['summary'])

    def test_per_file_mapping_options_and_all_failed_preserve_source(self):
        original=self.file('original.csv',[self.price()]);self.import_([original])
        before=self.snapshot()
        failed=self.import_([str(self.root/'missing.csv')]);self.assertEqual(failed['status'],'failed');self.assertEqual(self.snapshot(),before)
        path=self.root/'mapped.csv';path.write_text('ticker,day,o,h,l,c,v\n000001,2025-01-03,10,12,9,11,2\n',encoding='utf-8')
        mapping=dict(ticker='symbol',day='date',o='open',h='high',l='low',c='close',v='volume')
        opts=[dict(file=str(path),mapping=mapping,units=dict(volume='lots'))]
        row=self.preview([str(path)],fileOptions=opts)['files'][0]
        self.assertEqual(row['status'],'ready',row);self.assertEqual(row['sample'][0]['symbol'],'SZ000001')
        self.assertIn(dict(source='ticker',target='symbol'),row['columns'])
        self.assertEqual(row['sample'][0]['volume'],200.)
        self.assertEqual(self.import_([str(path)],fileOptions=opts)['status'],'completed')

    def test_all_existing_adapter_entries_validate_and_import_only_supported_choices(self):
        fixtures={
            'fund_flow':dict(symbol='SH600000',date='2025-01-02',fund_net_amount=100.,fund_net_ratio=.1),
            'chips':dict(symbol='SH600000',date='2025-01-02',chip_cost=10.,priceBasis='unadjusted'),
            'lhb':dict(symbol='SH600000',date='2025-01-02',lhb_net_amount=100.),
            'industry':dict(symbol='SH600000',effectiveDate='2025-01-02',industry='银行'),
            'corporate_actions':dict(id='action-1',symbol='SH600000',announcementDate='2025-01-01',recordDate='2025-01-02',exDate='2025-01-03',cashPerShare=.1,bonusRatio=0.,status='implemented'),
        }
        for kind,row in fixtures.items():
            with self.subTest(kind=kind):
                file=self.file(kind+'.csv',[row])
                self.assertEqual(self.preview([file],dataset=kind)['files'][0]['supportedConflictPolicies'],['replace'])
                self.assertEqual(self.import_([file],dataset=kind)['status'],'failed')
                result=self.import_([file],dataset=kind,conflictPolicy='replace',replaceConfirmed=True)
                self.assertEqual(result['status'],'completed',result)
        membership=self.file('members.csv',[dict(symbol='SH600000',startDate='2025-01-02',endDate='2025-01-03')])
        first=self.import_([membership],dataset='membership');second=self.import_([membership],dataset='membership')
        self.assertEqual(first['status'],'completed');self.assertEqual(second['status'],'completed')
        self.assertNotEqual(first['imports'][0]['membershipRef']['version'],second['imports'][0]['membershipRef']['version'])

    def test_repeat_counts_are_zero_and_invalid_units_fail_without_writes(self):
        source=self.file('input.csv',[self.price(amount=2.)])
        first=self.import_([source]);self.assertEqual(first['imports'][0]['newRows'],1)
        second=self.import_([source]);self.assertEqual(second['imports'][0]['newRows'],0)
        self.assertEqual(second['imports'][0]['filledCells'],0);self.assertEqual(second['imports'][0]['replacedRows'],0)
        before=self.snapshot()
        for units in (dict(volume='guessed'),dict(amount='dollars'),dict(price='CNY')):
            preview=self.preview([source],units=units)['files'][0]
            self.assertEqual(preview['status'],'failed');self.assertIn('单位',preview['message'])
            self.assertEqual(self.import_([source],units=units)['status'],'failed')
        self.assertEqual(self.snapshot(),before)

    def test_conflicting_group_declarations_reject_whole_file_without_mislabeling(self):
        original=self.file('old.csv',[self.price(amount=2.)]);self.import_([original])
        incoming=self.file('incoming.csv',[{**self.price(amount=3.),'close':11.}])
        for params in (dict(units=dict(volume='lots')),dict(units=dict(amount='ten_thousand_CNY')),dict(priceBasis='forward_adjusted')):
            with self.subTest(params=params):
                before=self.snapshot()
                self.assertEqual(self.preview([incoming],**params)['files'][0]['status'],'failed')
                self.assertEqual(self.import_([incoming],**params)['status'],'failed')
                self.assertEqual(self.snapshot(),before)
        saved=data.read_table(self.project).iloc[0]
        self.assertEqual(saved.volume,100.);self.assertEqual(saved.close,10.)
        self.assertNotIn('volumeUnit',saved.index);self.assertNotIn('priceBasis',saved.index)

    def test_unknown_replacement_cannot_retain_known_units_or_old_factor(self):
        original=self.file('known.csv',[self.price(amount=2.,factor=1.5)])
        self.import_([original],units=dict(volume='shares',amount='CNY'),priceBasis='forward_adjusted')
        incoming=self.file('unknown.csv',[{**self.price(amount=3.),'close':11.}])
        before=self.snapshot()
        result=self.import_([incoming],conflictPolicy='replace',replaceConfirmed=True)
        self.assertEqual(result['status'],'failed');self.assertEqual(self.snapshot(),before)
        result=self.import_([incoming],conflictPolicy='replace',replaceConfirmed=True,units=dict(volume='shares',amount='CNY'),priceBasis='forward_adjusted')
        self.assertEqual(result['status'],'failed');self.assertIn('完整的一组',result['imports'][0]['message']);self.assertEqual(self.snapshot(),before)
        complete=self.file('complete.csv',[{**self.price(amount=3.,factor=1.6),'close':11.}])
        result=self.import_([complete],conflictPolicy='replace',replaceConfirmed=True,units=dict(volume='shares',amount='CNY'),priceBasis='forward_adjusted')
        self.assertEqual(result['status'],'completed');self.assertEqual(data.read_table(self.project).iloc[0].factor,1.6)

    def test_fill_cannot_attach_new_factor_to_retained_ohlc(self):
        self.import_([self.file('old.csv',[self.price()])])
        before=self.snapshot()
        result=self.import_([self.file('factor.csv',[self.price(factor=1.5)])])
        self.assertEqual(result['status'],'failed');self.assertEqual(self.snapshot(),before)

    def test_metadata_only_and_null_amount_do_not_relabel_other_values(self):
        self.import_([self.file('old.csv',[self.price(amount=None,amountUnit='CNY')])])
        before=self.snapshot()
        unknown=self.file('unknown-amount.csv',[self.price(amount=10.)])
        self.assertEqual(self.import_([unknown])['status'],'failed');self.assertEqual(self.snapshot(),before)
        metadata=self.file('metadata.csv',[self.price(volumeUnit='shares')])
        self.assertEqual(self.import_([metadata])['status'],'failed');self.assertEqual(self.snapshot(),before)

    def test_failed_normalization_retains_columns_samples_and_mapping_can_recover(self):
        file=self.file('custom.csv',[dict(证券='SH600000',交易日='2025-01-02',开市价=10.,最高价=12.,最低价=9.,收市价=11.,交易量=100.)]*6)
        before=self.snapshot()
        with patch.object(pd,'read_csv',wraps=pd.read_csv) as read:
            row=self.preview([file])['files'][0]
            self.assertEqual(read.call_count,1)
        self.assertEqual(row['status'],'failed');self.assertEqual(row['rows'],6);self.assertEqual(len(row['sample']),5)
        self.assertIn(dict(source='证券',target='证券'),row['columns']);self.assertEqual(row['sample'][0]['证券'],'SH600000')
        self.assertEqual(self.snapshot(),before)
        mapping={'证券':'symbol','交易日':'date','开市价':'open','最高价':'high','最低价':'low','收市价':'close','交易量':'volume'}
        with patch.object(pd,'read_csv',wraps=pd.read_csv) as read:
            corrected=self.preview([file],mapping=mapping)['files'][0]
            self.assertEqual(read.call_count,1)
        self.assertEqual(corrected['status'],'ready');self.assertEqual(self.snapshot(),before)
        invalid=self.preview([file],mapping={'证券':'symbol','交易日':'symbol'})['files'][0]
        self.assertEqual(invalid['status'],'failed');self.assertEqual(len(invalid['sample']),5)
        self.assertIn(dict(source='交易日',target='symbol'),invalid['columns'])

    def test_source_metadata_failure_keeps_successful_worker_result_registered(self):
        source=self.file('good.csv',[self.price()])
        spec=dict(kind='data.import',projectId=self.pid,name='metadata failure',parameters=dict(files=[source]))
        with patch.object(self.service.jobs,'_start_next'):job=self.service.jobs.submit(spec)
        directory=self.root/'project/.research/runs'/job['id'];directory.mkdir(parents=True)
        write_json(directory/'request.json',dict(appData=str(self.service.store.root),job=job))
        original=data_imports.write_json
        def fail_source(path,value):
            if Path(path).name=='source.json':raise PermissionError('source metadata unavailable')
            return original(path,value)
        with patch.object(data_imports,'write_json',side_effect=fail_source):self.assertEqual(worker.run(directory),0)
        details=read_json(directory/'details.json')
        self.assertEqual(details['metadataStatus'],'failed');self.assertEqual(details['status'],'completed')
        self.assertEqual(details['failedFiles'],[]);self.assertEqual(details['imports'][0]['status'],'completed')
        self.assertTrue(any('无需重新导入成功文件' in message for message in details['warnings']))
        self.assertEqual(len(data.read_table(self.project)),1)
        write_json(directory/'process-exit.json',dict(cleanupConfirmed=True,returncode=0))
        self.service.jobs.recover_result(job['id'])
        saved=self.service.store.get('job',job['id']);self.assertEqual(saved['status'],'completed');self.assertEqual(saved['experimentId'],job['id'])
        self.assertIn('来源说明保存失败',self.service.store.experiment(self.pid,job['id'])['summary'])

    def test_partition_write_failure_message_is_not_used_for_preflight_failure(self):
        valid=self.file('valid.csv',[self.price()]);invalid=self.file('invalid.csv',[dict(unrelated=1)])
        with patch.object(data,'merge_table',side_effect=OSError('disk unavailable')):
            result=self.import_([valid,invalid])
        self.assertIn('可能已有部分分区写入；按原设置重试会重新校验',result['imports'][0]['message'])
        self.assertNotIn('部分分区',result['imports'][1]['message'])
