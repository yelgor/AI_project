import json
from pathlib import Path
import tempfile
import unittest
from scripts.run_experiments import report
from scripts.analyze_campaign import forecast_scores


class AnalysisTests(unittest.TestCase):
    def test_setup_failures_remain_in_success_denominator(self):
        config={'method':'B1','beta':0,'label':'shadow-a','pair_id':'shadow-a-0'}
        attempts=[{'status':'RECOVERED_WAIT','config':config,'metrics':{'success':True,'recovery_time_s':10}},
                  {'status':'SETUP_FAILED','config':config,'metrics':{}}]
        with tempfile.TemporaryDirectory() as tmp:
            report(attempts,Path(tmp));g=json.loads((Path(tmp)/'report.json').read_text())['groups']['B1/beta=0']
        self.assertEqual(g['total_runs'],2)
        self.assertEqual(g['success_fraction'],.5)
        self.assertEqual(g['success_fraction_after_loss'],1)

    def test_forecast_error_and_false_safe_conditioning(self):
        rows=[{'predicted_dbm':-45,'actual_dbm':-55,'threshold_dbm':-47,'std_db':None},
              {'predicted_dbm':-60,'actual_dbm':-60,'threshold_dbm':-47,'std_db':None}]
        result=forecast_scores(rows)
        self.assertEqual(result['mae_db'],5)
        self.assertEqual(result['false_safe_fraction'],.5)
        self.assertEqual(result['false_safe_given_predicted_safe'],1)
        self.assertEqual(result['predicted_safe_count'],1)


if __name__=='__main__':unittest.main()
