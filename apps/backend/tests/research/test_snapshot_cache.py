import tempfile,unittest,shutil,os
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from test_engines import sample_project
from v3_backend.research import engines,data

class SnapshotCacheTests(unittest.TestCase):
    def test_identical_relocated_snapshot_reuses_both_caches_changed_value_invalidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            source=Path(data.project_data(project)['path'])/'data'
            from v3_backend.research.input_snapshot import capture
            prepared={'inputStart':str(dates[0].date()),'inputEnd':str(dates[-1].date())}
            pa,_,_=capture(store,project,{},Path(project['path'])/'.research/runs/a',prepared)
            pb,_,_=capture(store,project,{},Path(project['path'])/'.research/runs/b',prepared)
            a=Path(pa['inputDataRoot'])/'data';b=Path(pb['inputDataRoot'])/'data'
            self.assertNotEqual(pa['inputCacheFiles'],pb['inputCacheFiles'])
            self.assertEqual(pa['inputCacheIdentity'],pb['inputCacheIdentity'])
            params={'factorIds':['momentum20'],'startDate':str(dates[30].date()),'endDate':str(dates[-1].date())}
            prices=engines.prepare(pa,root,lambda *_:None);values=engines.features(pa,params,prices)
            messages=[]
            prices=engines.prepare(pb,root,lambda _,m:messages.append(m))
            self.assertIn('复用项目Qlib缓存',messages)
            from qlib.data import D
            with patch.object(D,'features',side_effect=AssertionError('factor cache missed')):
                cached=engines.features(pb,params,prices)
            pd.testing.assert_frame_equal(values,cached)
            path=next((b/'prices').glob('*.parquet'));before=engines.input_cache_stamp(pb)
            frame=pd.read_parquet(path);frame.loc[0,'close']*=1.01;frame.to_parquet(path,index=False)
            self.assertNotEqual(before,engines.input_cache_stamp(pb))
            messages=[];engines.prepare(pb,root,lambda _,m:messages.append(m))
            self.assertNotIn('复用项目Qlib缓存',messages)
            # Source updates cannot change the retained identity of an earlier snapshot.
            source_file=next((source/'prices').glob('*.parquet'));os.utime(source_file,None)
            reproduced,_,_=capture(store,pa,{},Path(project['path'])/'.research/runs/c',prepared)
            self.assertEqual(reproduced['inputCacheIdentity'],pa['inputCacheIdentity'])
            self.assertEqual(engines.input_cache_stamp(reproduced),engines.input_cache_stamp(pa))
