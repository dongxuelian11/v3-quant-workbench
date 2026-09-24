"""Rule observations must explain persisted execution without changing trading."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
import pyarrow.parquet as pq
from openpyxl import load_workbook
from test_engines import sample_project
from v3_backend.research import accounting, engines
from v3_backend.research.strategy import decide_day
from v3_backend.research.rule_diagnostics import Writer
from v3_backend.research.storage import write_json
from v3_backend.research.server import Service
from v3_backend.research.execution import cost_config


def condition(field='rawClose', op='gt', value=0):
    return dict(field=field, op=op, value=value)


def rule(action='entry', conditions=None, weight=.02):
    return dict(id='duplicate-is-allowed', action=action, weight=weight,
                conditions=[condition()] if conditions is None else conditions)


class RuleDiagnosticsTest(unittest.TestCase):
    def test_conditions_short_circuit_skips_and_unchanged_decision(self):
        day = pd.Timestamp('2025-01-06')
        codes = ['SH600000', 'SH600001']
        prices = pd.DataFrame([dict(date=day, symbol=s, rawClose=10.) for s in codes])
        context = dict(date=day, prices=prices, scores=pd.Series(1., index=codes),
            cash=1000., holdings={'SH600000':dict(quantity=100, costPrice=10.)},
            features=pd.DataFrame({'nullValue':[None, None], 'nanValue':[float('nan')]*2,
                                   'infinity':[float('inf'), -float('inf')]}, index=codes))
        rules = [rule('exit'), rule('add'), rule(),
                 rule(conditions=[condition(value=20), condition('not-a-field')]),
                 rule(conditions=[condition('nullValue'), condition('not-a-field')]),
                 rule(conditions=[condition('nanValue')]), rule(conditions=[]),
                 rule(conditions=[condition('infinity')]),
                 rule(conditions=[condition(value=20),condition(value=float('nan')),None])]
        plain = decide_day(context, dict(rules=rules))
        traced = decide_day(context, dict(rules=rules), collect_diagnostics=True)
        rows = traced.pop('ruleDiagnostics')
        pd.testing.assert_series_equal(plain.pop('scores'), traced.pop('scores'))
        self.assertEqual(plain, traced)
        by_key = {(r['symbol'],r['ruleIndex']):r for r in rows}
        self.assertEqual(by_key[codes[0],1]['skipReason'],'exit_priority')
        self.assertEqual(by_key[codes[0],2]['skipReason'],'already_held')
        self.assertEqual(by_key[codes[1],0]['skipReason'],'not_held')
        failed = by_key[codes[1],3]
        self.assertEqual(failed['ruleState'],'not_matched')
        self.assertEqual([c['conditionState'] for c in failed['conditions']],['false','not_evaluated'])
        for i in (4,5):
            self.assertEqual(by_key[codes[1],i]['ruleState'],'unknown')
            self.assertEqual(by_key[codes[1],i]['conditions'][0]['valueState'],'missing')
        self.assertEqual(by_key[codes[1],6]['ruleState'],'matched')
        self.assertEqual(by_key[codes[1],7]['conditions'][0]['valueState'],'negative_infinity')
        from v3_backend.research.rule_diagnostics import json_text
        json_text(rows)  # Short-circuited NaN threshold is represented, never evaluated.
        self.assertEqual(by_key[codes[1],8]['conditions'][2]['thresholdState'],'missing')
        self.assertEqual(by_key[codes[1],8]['conditions'][2]['conditionState'],'not_evaluated')
        # Reached configuration errors still fail; diagnostics cannot turn them into unknown.
        for bad in (condition('not-a-field'), condition(op='bad'), condition(value=float('inf'))):
            with self.assertRaises(ValueError):
                decide_day(context, dict(rules=[rule(conditions=[bad])]), collect_diagnostics=True)

    def test_writer_empty_and_failure_never_publish_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            with Writer(directory) as empty:
                pass
            self.assertEqual(empty.capability()['rowCount'],0)
            self.assertEqual(pq.ParquetFile(empty.path).metadata.num_rows,0)
            failure = Path(directory)/'failure'
            failure.mkdir()
            with self.assertRaisesRegex(OSError,'disk full'):
                with Writer(failure) as broken:
                    raise OSError('disk full')
            self.assertFalse(broken.path.exists())
            self.assertTrue(broken.temporary.exists())
            with self.assertRaises(ValueError):broken.capability()

    def test_real_backtest_persisted_query_export_and_old_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, store = sample_project(Path(directory))
            output = Path(project['path'])/'.research/runs/diagnostic-run'
            output.mkdir(parents=True)
            prices = engines.prepare(project, output, lambda *_:None)
            # This generated fixture explicitly has no adjustments.
            prices['factor'] = 1.
            for field in ('open','high','low','close'):
                prices['raw'+field.title()] = prices[field]
            prices['rawPreclose'] = prices.groupby('symbol').close.shift(1).fillna(prices.close)
            prices['tradestatus'] = 1
            start = dates[-5]
            # Exercise the real exchange's zero known-volume and untradable paths.
            prices.loc[prices.symbol.eq('SH600002') & prices.date.eq(start),'volume'] = 0.
            prices.loc[prices.symbol.eq('SH600001') & prices.date.eq(dates[-4]),'tradestatus'] = 0
            prices.loc[prices.symbol.eq('SH600011'),'volume'] = 0.
            entry_conditions = [condition(), condition('volume')]
            rules = [rule('exit'),rule('add'),rule(conditions=entry_conditions),
                rule(conditions=[condition(value=10000),condition('never-evaluated')]),
                rule(conditions=[condition('costPrice'),condition(value=10000)]),
                rule(conditions=entry_conditions)]
            params = dict(template='multi_factor',rules=rules,capital=1000000,topN=3,
                startDate=str(start.date()),endDate=str(dates[-1].date()),
                initialPositions=[dict(symbol='SH600000',quantity=1000,sellableQuantity=1000,costPrice=20.)])
            observed = {}
            actual_run = accounting.run_backtest
            def compare_runs(*args, **kwargs):
                baseline = actual_run(*args, **{**kwargs,'diagnostic_sink':None})
                traced = actual_run(*args, **kwargs)
                self.assertEqual(baseline['account'],traced['account'])
                self.assertEqual(baseline['targets'],traced['targets'])
                pd.testing.assert_frame_equal(baseline['report'],traced['report'])
                for key in ('trades','unfilled'):
                    stripped = [{k:v for k,v in row.items() if k not in {'signalDate','orderId'}}
                                for row in traced[key]]
                    self.assertEqual(baseline[key],stripped)
                observed.update(traced)
                return traced
            with patch('v3_backend.research.accounting.run_backtest',side_effect=compare_runs):
                result = engines.backtest(project,params,output,lambda *_:None,prices=prices,store=store)
            self.assertEqual(result['details']['ruleDiagnostics']['status'],'available')
            path = output/'rule_diagnostics.parquet'
            frame = pd.read_parquet(path)
            self.assertEqual(len(frame),4*12*len(rules))
            self.assertEqual(result['details']['ruleDiagnostics']['rowCount'],len(frame))
            self.assertGreater(pq.ParquetFile(path).metadata.num_row_groups,1)
            self.assertTrue({'matched','not_matched','unknown','skipped'}.issubset(set(frame.ruleState)))
            self.assertTrue({'partial','rejected','no_order'}.issubset(set(frame.orderState)),set(frame.orderState))
            first = frame[frame.date.eq(str(start.date()))]
            reject = first[first.symbol.eq('SH600001')]
            self.assertTrue(reject.orderState.eq('rejected').all())
            self.assertTrue(reject.orderId.notna().all())
            self.assertGreater(len(observed['trades']),0)
            self.assertTrue(all('orderId' in row and 'signalDate' in row for row in observed['unfilled']))
            order_id = reject.orderId.iloc[0]
            write_json(output/'details.json',result['details'])
            write_json(output/'project.json',project)
            experiment = dict(id='diagnostic-run',name='rule diagnostic sample',kind='backtest.run',
                metrics=result['metrics'],parameters=result['parameters'],artifacts=result['artifacts'],
                summary=result['summary'],createdAt='2025-01-01')
            store.save_experiment(project['id'],experiment)
            service = Service(Path(directory)/'app')
            try:
                query = dict(projectId=project['id'],experimentId=experiment['id'],table='rule_diagnostics',
                    symbol='SH600001',startDate=str(start.date()),endDate=str(start.date()),limit=2)
                first_page = service.request('experiments.table',query)
                self.assertEqual(first_page['total'],len(rules))
                self.assertEqual(len(first_page['rows']),2)
                second_page = service.request('experiments.table',{**query,'offset':2})
                self.assertNotEqual(first_page['rows'][0]['ruleIndex'],second_page['rows'][0]['ruleIndex'])
                linked = service.request('experiments.table',dict(projectId=project['id'],experimentId=experiment['id'],
                    table='unfilled',orderId=order_id))
                self.assertGreater(linked['total'],0)
                self.assertTrue(all(r['signalDate']==str(start.date()) for r in linked['rows']))
                # Changing current data must have no effect on stored values or pagination.
                from v3_backend.research.data import merge_table,read_table
                current = read_table(project)
                current['close'] = current.close*2
                merge_table(project,current,'prices')
                with patch('v3_backend.research.strategy.decide_day',side_effect=AssertionError('must not recompute')):
                    self.assertEqual(first_page,service.request('experiments.table',query))
                    csv = service.request('exports.create',dict(projectId=project['id'],experimentId=experiment['id'],
                        format='csv',table='rule_diagnostics'))
                    xlsx = service.request('exports.create',dict(projectId=project['id'],experimentId=experiment['id'],format='xlsx'))
                exported = pd.read_csv(csv['path'])
                self.assertEqual(len(exported),len(frame))
                self.assertEqual(exported.conditionsJson.tolist(),frame.conditionsJson.tolist())
                book = load_workbook(xlsx['path'],read_only=True)
                try:
                    sheet = next(sheet for sheet in book if sheet.title.endswith('rule_diagnostics'))
                    self.assertEqual(sum(1 for _ in sheet.values),len(frame)+1)
                finally:book.close()
                legacy = {**experiment,'id':'legacy','artifacts':[]}
                store.save_experiment(project['id'],legacy)
                legacy_details = service.request('experiments.get',dict(projectId=project['id'],experimentId='legacy'))
                self.assertNotIn('ruleDiagnostics',legacy_details['details'])
                with self.assertRaisesRegex(ValueError,'没有此数据表'):
                    service.request('experiments.table',{**query,'experimentId':'legacy'})
            finally:service.close()

    def test_stream_failure_long_export_and_empty_order_query(self):
        from v3_backend.research.rule_diagnostics import execution_table
        from v3_backend.research.table_reader import page
        from v3_backend.research.result_export import export
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observation = dict(date='2025-01-06',symbol='SH600000',ruleId='r',ruleIndex=0,
                action='entry',ruleState='not_matched',skipReason=None,beforeWeight=0.,targetWeight=0.,
                conditions=[dict(conditionIndex=i,field='rawClose',op='lt',threshold=0.,value=10.,
                                 conditionState='false',valueState='present') for i in range(400)])
            decision = dict(conflicts=['组合约束冲突示例'],ruleDiagnostics=[observation])
            with Writer(root) as writer:
                writer.write_day(decision,{},'2025-01-07')
            store = SimpleNamespace(artifact_path=lambda project,artifact:Path(artifact['path']))
            experiment = dict(id='long',metrics={},artifacts=[writer.artifact()])
            csv = export(store,None,experiment,root,'csv','rule_diagnostics')
            self.assertEqual(len(json.loads(pd.read_csv(csv['path']).conditionsJson.iloc[0])),400)
            self.assertEqual(json.loads(pd.read_csv(csv['path']).constraintReasonsJson.iloc[0]),decision['conflicts'])
            with self.assertRaisesRegex(ValueError,'CSV'):
                export(store,None,experiment,root,'xlsx')
            self.assertEqual(list(root.glob('*.xlsx')),[])
            for kind in ('trades','unfilled'):
                path = root/(kind+'.parquet')
                execution_table([],kind).to_parquet(path,index=False)
                self.assertEqual(page(path,{'orderId':'missing'},kind)['total'],0)
            failure = root/'failure'
            failure.mkdir()
            with self.assertRaisesRegex(OSError,'write failed'):
                with Writer(failure) as broken:
                    broken.write_day(decision,{},'2025-01-07')
                    with patch.object(broken,'_write',side_effect=OSError('write failed')):
                        broken.write_day(decision,{},'2025-01-08')
            self.assertFalse(broken.complete)
            self.assertFalse(broken.path.exists())
            self.assertTrue(broken.temporary.exists())

    def test_order_links_filled_and_direct_missing_market(self):
        from qlib.config import C
        C.set(region='cn')
        dates = pd.bdate_range('2025-01-06',periods=2)
        prices = pd.DataFrame([dict(date=d,symbol='SH600000',rawOpen=10.,rawClose=10.,
            rawPreclose=10.,open=10.,close=10.,volume=1000000.,factor=1.,isST=0,tradestatus=1)
            for d in dates])
        decision = dict(date=str(dates[0].date()),quantities={'SH600000':100.,'SH600001':100.},reasons=[])
        result = accounting.advance_day(accounting.create(10000),dates[1],prices,decision,cost_config({}),
                                        collect_orders=True)
        orders = {row['symbol']:row for row in result['_diagnosticOrders']}
        self.assertEqual(orders['SH600000']['state'],'filled')
        self.assertEqual(orders['SH600001']['state'],'rejected')
        self.assertEqual(result['trades'][0]['orderId'],orders['SH600000']['orderId'])
        self.assertEqual(result['unfilled'][0]['orderId'],orders['SH600001']['orderId'])


if __name__ == '__main__':
    unittest.main()
