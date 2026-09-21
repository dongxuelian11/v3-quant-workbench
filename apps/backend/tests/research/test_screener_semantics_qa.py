"""Independent small-sample screener semantics; no market/model calls or full run."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from v3_backend.research.server import Service
from v3_backend.research import history, screeners
from v3_backend.research.screen_conditions import evaluate, weighted_scores


class ScreenerSemanticsQA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = Service(self.root / 'app')
        self.store = self.service.store
        self.project = self.store.create_project(self.root / 'source', 'QA source')
        self.network_guard = patch('socket.socket.connect', side_effect=AssertionError('QA forbids network'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def plan(self, **changes):
        value = dict(name='QA plan', mode='conditions', universe=dict(name='QA range', source='all',
            symbols=[], excludeST=False, minListingDays=0), conditions=dict(id='root', match='all', children=[]),
            factors=[], assets=[], rankingReference='base')
        value.update(changes)
        return value

    def save(self, value):
        return self.service.request('screeners.save', {'plan': value})

    def submit_only(self, plan):
        with patch.object(self.service.jobs, 'submit', return_value={'id':'captured-submission'}) as submitted:
            self.service.request('screeners.run', {'planId':plan['id']})
            return submitted.call_args

    def test_legacy_migration_does_not_add_base_exclusions(self):
        old = dict(id='legacy', name='Existing query', query={'symbols':['600000'], 'search':'银行',
            'filters':[], 'watchlistId':'old-list'})
        migrated = screeners.normalize(old)
        self.assertFalse(migrated['universe']['excludeST'], 'migration added an ST exclusion absent in the old query')
        self.assertEqual(migrated['universe']['minListingDays'], 0)
        self.assertEqual(migrated['universe']['symbols'], ['SH600000'])
        self.assertEqual(migrated['query']['search'], '银行')
        self.assertEqual(migrated['query']['watchlistId'], 'old-list')

    def test_three_value_groups_and_temporal_decisive_signal(self):
        index = pd.MultiIndex.from_product([pd.date_range('2026-01-05', periods=2), ['A']], names=['date','symbol'])
        panel = pd.DataFrame({'value':[1., np.nan], 'zero':[0., 0.]}, index=index)
        rule = dict(id='v', field='value', operator='gt', value=0)
        group = dict(id='root', match='any', children=[rule, dict(id='yes',field='zero',operator='eq',value=0)])
        mask, _ = evaluate(panel, group)
        self.assertTrue(bool(mask.iloc[-1]), 'known true OR unknown must remain true')
        temporal, _ = evaluate(panel, {**rule, 'occurrence':'any', 'window':2})
        self.assertFalse(pd.isna(temporal.iloc[-1]), 'a known signal in the window was lost because another session is unknown')
        self.assertTrue(bool(temporal.iloc[-1]))

    def test_legacy_search_and_watchlist_keep_the_same_included_set(self):
        from v3_backend.research import data, market, screening_run
        prices = pd.DataFrame([dict(symbol=code, name=name, date=pd.Timestamp('2020-01-02'),
            open=10.,high=10.,low=10.,close=10.,volume=100.,isST=0,listingDate='2010-01-01')
            for code,name in [('SH600000','甲银行'),('SH600001','乙银行'),('SH600002','钢铁')]])
        data.merge_table(self.project, prices, 'prices', return_all=False)
        watch = self.service.request('watchlists.save', {'watchlist':dict(name='Legacy scope',symbols=['600000','600002'])})
        old = dict(id='legacy-query',name='Legacy filter',query=dict(watchlistId=watch['id'],search='银行',date='2020-01-02',filters=[]))
        expected = set(market.filter_frame(prices, old['query'], [watch]).symbol)
        self.store.put('screener', old)
        calls = self.submit_only(old)
        target = calls.kwargs['frozen_project']
        plan = calls.args[0]['parameters']['plan']
        folder = Path(target['path']) / '.research/runs/qa-legacy-screen'
        with patch('v3_backend.research.preparation.trading_dates', side_effect=AssertionError('no network calendar')):
            result = screening_run.run(self.store,target,dict(plan=plan,allowPartial=True),folder,lambda *_:None)
        frame = pd.read_parquet(result['artifacts'][0]['path'])
        actual = set(frame.loc[frame.status.eq('included'),'symbol'])
        self.assertEqual(actual, expected)

    def test_rank_reference_and_factor_direction_once(self):
        index = pd.MultiIndex.from_product([pd.to_datetime(['2026-01-05']), ['A','B','C']], names=['date','symbol'])
        panel = pd.DataFrame({'value':[10.,20.,30.], 'eligible':[1.,1.,0.]}, index=index)
        rule = dict(id='root', match='all', children=[dict(id='rank',field='value',operator='rank_top',value=1),
            dict(id='eligible',field='eligible',operator='eq',value=1)])
        base, details = evaluate(panel, rule)
        self.assertFalse(base.any())
        self.assertEqual(details['rank']['ranks'].tolist(), [3.,2.,1.])
        pre, _ = evaluate(panel, rule, panel.eligible.eq(1))
        self.assertEqual(pre.fillna(False).tolist(), [False,True,False])
        scores, _ = weighted_scores(panel,[dict(id='value',direction=-1,weight=2)],pd.Series(True,index=index))
        np.testing.assert_allclose(scores.to_numpy(), [1.,2/3,1/3])

    def test_plan_versions_and_watchlist_append_preserve_notes(self):
        initial = self.save(self.plan())
        renamed = self.save({**initial, 'name':'Renamed', 'favorite':True})
        self.assertEqual(renamed['version'], initial['version'])
        changed = self.save({**renamed, 'date':'2026-01-05'})
        self.assertEqual(changed['version'], initial['version']+1)
        watch = self.service.request('watchlists.save', {'watchlist':dict(name='QA list', symbols=['600000'],
            notes={'SH600000':'Keep this note'}, note='Group note')})
        updated = self.service.request('watchlists.add', dict(id=watch['id'], symbols=['600000','600001'],mode='append'))
        self.assertEqual(updated['symbols'], ['SH600000','SH600001'])
        self.assertEqual(updated['notes'], watch['notes'])
        self.assertEqual(updated['note'], watch['note'])

    def test_strategy_asset_with_data_directory_can_submit(self):
        asset = next(a for a in self.service.request('screeners.assets',{}) if a['kind']=='strategy' and a['projectId']==self.project['id'])
        self.assertTrue(asset['available'])
        saved = self.save(self.plan(mode='strategy', assets=[asset]))
        calls = self.submit_only(saved)
        self.assertIsNotNone(calls)
        self.assertEqual(self.store.project(self.project['id']), self.project)

    def test_saved_asset_version_cannot_silently_copy_changed_source(self):
        code = Path(self.project['path']) / 'factor.py'
        code.write_text('version = 1\n', encoding='utf-8')
        asset = dict(id='qa-factor', kind='factor', name='QA factor', projectId=self.project['id'],
            revision='selected-v1', available=True, snapshot=dict(factorId='custom', customFactor={'id':'custom','codePath':'factor.py'}))
        saved = self.save(self.plan(mode='factors',assets=[asset],factors=[dict(id='custom',direction=1,weight=1)]))
        code.write_text('version = 2\n', encoding='utf-8')
        try:
            calls = self.submit_only(saved)
        except ValueError:
            return  # Explicit stale-version rejection is also safe.
        submitted_plan = calls.args[0]['parameters']['plan']
        copied = submitted_plan['assets'][0]['snapshot']['customFactor']['codePath']
        root = Path(calls.kwargs['frozen_project']['path'])
        self.assertEqual((root / copied).read_text(encoding='utf-8'), 'version = 1\n',
            'selected-v1 silently executed source code edited after that plan was saved')

    def test_membership_copy_and_cross_project_rejection(self):
        source = deepcopy(self.project)
        history.import_membership(source, pd.DataFrame([dict(symbol='600000',startDate='2020-01-01',endDate=None)]))
        source = self.store.save_project(source)
        saved = self.save(self.plan(universe=source['universe'], dataProjectId=source['id']))
        calls = self.submit_only(saved)
        target = calls.kwargs['frozen_project']
        self.assertEqual(history.members(target,'2020-01-02'), {'SH600000'})
        self.assertEqual(self.store.project(source['id']), source)
        other = self.store.create_project(self.root / 'other','Other')
        invalid = self.save({**saved, 'dataProjectId':other['id']})
        with self.assertRaises(ValueError), patch.object(self.service.jobs,'submit',side_effect=AssertionError('must not submit')):
            self.service.request('screeners.run', {'planId':invalid['id']})

    def seed_prices(self):
        from v3_backend.research import data
        frame = pd.DataFrame([dict(symbol=code,name=code,date=pd.Timestamp('2020-01-02'),
            open=10.,high=10.,low=10.,close=10.,volume=100.,isST=0,listingDate='2010-01-01')
            for code in ['SH600000','SH600001']])
        data.merge_table(self.project,frame,'prices',return_all=False)
        return frame

    def execute_capture(self, calls, name, partial=True):
        from v3_backend.research import screening_run
        project = calls.kwargs['frozen_project']
        params = {**calls.args[0]['parameters'], 'allowPartial':partial}
        folder = Path(project['path']) / '.research/runs' / name
        return screening_run.run(self.store,project,params,folder,lambda *_:None)

    def test_empty_legacy_watchlist_does_not_expand_to_observed_market(self):
        self.seed_prices()
        watch = self.service.request('watchlists.save', {'watchlist':dict(name='Empty',symbols=[])})
        old = dict(id='legacy-empty',name='Empty saved list',query=dict(watchlistId=watch['id'],date='2020-01-02',filters=[]))
        self.store.put('screener',old)
        calls = self.submit_only(old)
        try:
            result = self.execute_capture(calls,'qa-empty-list')
        except ValueError:
            return  # Explicit empty-scope rejection is acceptable; broadening is not.
        self.assertEqual(result['metrics']['included'],0,'empty watchlist expanded into cached securities')

    def test_formal_all_scope_cannot_claim_complete_observed_only_market(self):
        self.seed_prices()
        saved = self.save(self.plan(date='2020-01-02'))
        calls = self.submit_only(saved)
        prepared = dict(inputStart='2020-01-02',inputEnd='2020-01-02',effectiveStart='2020-01-02',effectiveEnd='2020-01-02')
        # Isolate the final coverage boundary, without triggering a market-data repair.
        with patch('v3_backend.research.screening_run._calendar',return_value=['2020-01-02']), patch('v3_backend.research.preparation.prepare',side_effect=lambda store,job,project,directory,progress:(job['spec']['parameters'],prepared)):
            with self.assertRaises(ValueError):
                self.execute_capture(calls,'qa-formal-all',partial=False)

    def test_strategy_without_account_does_not_fabricate_missing_predictions(self):
        from v3_backend.research.storage import write_json
        self.seed_prices()
        model_dir = Path(self.project['path']) / '.research/runs/qa-model'
        model_dir.mkdir(parents=True)
        prediction = model_dir / 'predictions.parquet'
        pd.DataFrame(dict(date=pd.to_datetime(['2020-01-02']*2),symbol=['SH600000','SH600001'],score=[.8,.2])).to_parquet(prediction,index=False)
        self.store.save_experiment(self.project['id'],dict(id='qa-model',projectId=self.project['id'],kind='model.train',
            name='Complete predictions',createdAt='',parameters={},metrics={},artifacts=[dict(name='test_predictions',type='parquet',path=str(prediction))]))
        model = next(a for a in self.service.request('screeners.assets',{}) if a['kind']=='model')
        strategy = dict(id='qa-strategy',kind='strategy',name='Exit rules require account',revision='v1',available=True,
            projectId=self.project['id'],snapshot=dict(settings={'backtest':dict(template='model_score',topN=2,
                rules=[dict(action='exit',conditions=[dict(field='score',op='lt',value=.5)])])}))
        saved = self.save(self.plan(mode='strategy',date='2020-01-02',assets=[model,strategy],
            universe=dict(name='Both',source='manual',symbols=['SH600000','SH600001'],excludeST=False,minListingDays=0)))
        calls = self.submit_only(saved)
        try:
            result = self.execute_capture(calls,'qa-no-account')
        except ValueError as exc:
            self.assertRegex(str(exc),'账户|持仓|候选')
            return
        frame = pd.read_parquet(result['artifacts'][0]['path'])
        self.assertEqual(result['metrics']['missing'],0,
            'complete model predictions masked by empty-account targets were mislabeled missing: '+str(frame.to_dict('records')))

    def test_project_save_preserves_current_membership_state(self):
        stale = deepcopy(self.project)
        current = deepcopy(self.project)
        current['universe']['membershipRef'] = dict(poolId='pool',version='new',source='import')
        self.store.save_project(current)
        stale['universe']['name']='Edited name'
        saved = self.service.request('projects.save',dict(project=stale,preserveMembershipRef=True))
        self.assertEqual(saved['universe']['membershipRef']['version'],'new')
        self.assertEqual(saved['universe']['name'],'Edited name')
        removed = deepcopy(saved); removed['universe'].pop('membershipRef')
        self.store.save_project(removed)
        saved['universe']['name']='After removal'
        final = self.service.request('projects.save',dict(project=saved,preserveMembershipRef=True))
        self.assertNotIn('membershipRef', final['universe'])
        self.assertEqual(final['universe']['name'],'After removal')


if __name__ == '__main__':
    unittest.main()
