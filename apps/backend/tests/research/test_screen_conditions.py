import unittest
import numpy as np
import pandas as pd
from v3_backend.research.screen_conditions import evaluate, weighted_scores, validate


class ScreenerConditionsTest(unittest.TestCase):
    def panel(self):
        index = pd.MultiIndex.from_product([pd.date_range('2026-01-05', periods=3), ['A','B','C']], names=['date','symbol'])
        return pd.DataFrame({'value':[1,2,3, 3,np.nan,1, 4,1,2], 'other':[3,2,1, 1,2,3, 2,3,1]},index=index)

    def test_rank_uses_explicit_reference_not_other_condition(self):
        panel = self.panel()
        rule = {'id':'group','match':'all','children':[
            {'id':'rank','field':'value','operator':'rank_top','value':1},
            {'id':'filter','field':'other','operator':'gt','value':1}]}
        mask, details = evaluate(panel,rule)
        self.assertFalse(mask.iloc[:3].any())
        self.assertEqual(details['rank']['ranks'].iloc[:3].tolist(),[3,2,1])
        reference = panel.other.gt(1)
        mask,_ = evaluate(panel,rule,reference)
        self.assertTrue(mask.loc[(pd.Timestamp('2026-01-05'),'B')])

    def test_missing_session_breaks_cross_and_consecutive_certainty(self):
        panel=self.panel()
        crossing,_=evaluate(panel,{'id':'cross','field':'value','operator':'cross_up','value':1.5})
        self.assertTrue(crossing.loc[(pd.Timestamp('2026-01-06'),'A')])
        self.assertTrue(pd.isna(crossing.loc[(pd.Timestamp('2026-01-07'),'B')]))
        consecutive,_=evaluate(panel,{'id':'days','field':'value','operator':'gt','value':0,'window':2,'occurrence':'all'})
        self.assertTrue(pd.isna(consecutive.loc[(pd.Timestamp('2026-01-07'),'B')]))
        self.assertTrue(consecutive.loc[(pd.Timestamp('2026-01-07'),'A')])

    def test_direction_once_and_missing_not_zero(self):
        panel=self.panel(); ref=pd.Series(True,index=panel.index)
        score,parts=weighted_scores(panel,[{'id':'value','direction':-1,'weight':1},{'id':'other','direction':1,'weight':1}],ref)
        self.assertAlmostEqual(score.iloc[0],1)
        self.assertAlmostEqual(score.iloc[2],1/3)
        self.assertTrue(pd.isna(score.iloc[4]))
        constant=panel.assign(value=1)
        score,_=weighted_scores(constant,[{'id':'value','direction':1,'weight':1}],ref)
        self.assertTrue(score.isna().all())

    def test_invalid_reference_and_range_rejected(self):
        with self.assertRaises(ValueError):
            validate({'id':'r','field':'value','operator':'rank_top','value':1},ranking_allowed=False)
        with self.assertRaises(ValueError):
            validate({'id':'r','field':'value','operator':'rank_top','compareField':'other'})
        with self.assertRaises(ValueError):
            validate({'id':'r','field':'value','operator':'between','value':2,'upper':1})


if __name__=='__main__': unittest.main()
