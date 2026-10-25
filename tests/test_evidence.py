import hashlib
import json
import unittest

import numpy as np

from app.evidence import EvidenceLibrary, LIBRARY, ROOT
from app.radio_maps import RadioMap
from scripts.build_learning_evidence import fixed_holdout


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library=EvidenceLibrary()
        cls.overview=cls.library.overview()
        cls.learning=json.loads((LIBRARY/'learning-evidence.json').read_text())

    def test_gpr_denominators_and_missing_hardware_are_explicit(self):
        self.assertEqual([(c['gpr_successes'],c['gpr_total'],c['total']) for c in self.overview['cohorts']],
                         [(39,40,100),(18,20,20),(20,20,30)])
        self.assertEqual(self.overview['hardware_validation'],{'available':False,'runs':0})
        self.assertEqual(self.overview['data_origin'],'recorded_simulation')

    def test_full_gpr_demo_contains_outbound_learning_and_recovery_without_seed(self):
        e=self.overview['examples']['gpr_demo'];r=self.library.run(e['cohort'],e['experiment_id'])
        self.assertEqual(r['manifest']['config']['method'],'GPR-pathloss')
        self.assertFalse(r['manifest']['config']['history_from'])
        self.assertEqual(r['manifest']['status'],'RECOVERED_WAIT')
        modes=[e['mode'] for e in r['timeline'] if e['kind']=='mode']
        for mode in ('SURVEY','LINK_DEGRADED','RECOVERY','RECOVERED_WAIT'):self.assertIn(mode,modes)
        self.assertLess(modes.index('SURVEY'),modes.index('RECOVERY'))
        self.assertGreater(sum(e['kind']=='map' for e in r['timeline']),50)
        self.assertEqual(r['manifest']['metrics']['observation_count'],113)

    def test_responsive_demo_brakes_before_target_and_before_deep_anchor(self):
        e=self.overview['examples']['responsive_demo'];r=self.library.run(e['cohort'],e['experiment_id'])
        self.assertEqual(r['manifest']['config']['loss_policy'],'responsive')
        self.assertEqual(r['manifest']['status'],'RECOVERED_WAIT')
        brake=next(e for e in r['timeline'] if e['kind']=='brake')
        target=next(e for e in r['timeline'] if e['kind']=='target')
        self.assertLess(brake['sequence'],target['sequence'])
        self.assertLess(np.linalg.norm(brake['pose']['linear_velocity']),.03)
        self.assertGreater(self.overview['responsive_demo']['distance_to_anchor_at_first_weak_m'],1)
        self.assertTrue(self.library.file('acceptance/responsive-office.zip').is_file())

    def test_failed_and_repeated_gpr_runs_use_identical_seed_measurements(self):
        rows=[]
        for name in ('gpr_failure','gpr_repeat'):
            e=self.overview['examples'][name]
            rows.append(self.library.run(e['cohort'],e['experiment_id']))
        self.assertEqual([r['manifest']['status'] for r in rows],['FAILED','RECOVERED_WAIT'])
        self.assertEqual(rows[0]['manifest']['radio_field_sha256'],rows[1]['manifest']['radio_field_sha256'])
        def prefix(run):
            result=[]
            for event in run['timeline']:
                if event['kind']=='mode' and event['mode']=='LINK_DEGRADED':break
                if event['kind']=='observation':
                    m=event['measurement'];result.append((m['position_m'],m['rssi_dbm'],m['sim_time_s']))
            return result
        self.assertGreater(len(prefix(rows[0])),30)
        a,b=prefix(rows[0]),prefix(rows[1])
        self.assertEqual([(p,v) for p,v,t in a],[(p,v) for p,v,t in b])
        # Warm Gazebo clocks differ; the controller rebases the same history.
        np.testing.assert_allclose([t-a[-1][2] for p,v,t in a],
                                   [t-b[-1][2] for p,v,t in b],atol=1e-9,rtol=0)

    def test_archive_access_rejects_unlisted_paths_and_identity(self):
        for value in ('../README.md','/etc/passwd','../../demo.zip','unknown.json'):
            with self.assertRaises(FileNotFoundError):self.library.file(value)
        with self.assertRaises(ValueError):self.library.run_bytes('../../baseline-100','20261025T091242Z-4655ff46')
        with self.assertRaises(ValueError):self.library.run_bytes('baseline-100','../../README')
        with self.assertRaises(FileNotFoundError):self.library.run_bytes('baseline-100','20261025T000000Z-00000000')
        for name in ('learning-evidence.json','map-scores.csv','baseline-100-trials.csv'):
            self.assertTrue(self.library.file(name).is_file())

    def test_fixed_holdout_excludes_neighbours_of_future_samples(self):
        observations=[{'position_m':[0,0,1],'rssi_dbm':-40},
                      {'position_m':[10,0,1],'rssi_dbm':-60}]
        mask=fixed_holdout([[0,0,1],[10.2,0,1],[5,0,1]],observations)
        self.assertEqual(mask.tolist(),[False,False,True])

    def test_archived_reference_matches_recorded_field_and_remains_evaluation_only(self):
        e=self.overview['examples']['gpr_success'];run=self.library.run(e['cohort'],e['experiment_id'])
        ref=self.library.reference_for_run(e['cohort'],e['experiment_id'])
        self.assertEqual(ref['manifest']['radio_field_sha256'],run['manifest']['radio_field_sha256'])
        self.assertTrue(ref['manifest']['parameters']['evaluation_only'])
        self.assertFalse(ref['manifest']['parameters']['controller_training'])
        class WrongField(EvidenceLibrary):
            def reference(self,name):return {'manifest':{'radio_field_sha256':'different'}}
        with self.assertRaises(ValueError):WrongField().reference_for_run(e['cohort'],e['experiment_id'])

    def test_curves_do_not_reuse_frozen_test_and_have_source_fingerprints(self):
        self.assertEqual(len(self.learning['fields']),8)
        self.assertEqual({f['split'] for f in self.learning['fields']},{'train','validation'})
        self.assertFalse(any(f['name'].startswith('courtyard') for f in self.learning['fields']))
        for key,path in (('source_archive_sha256',LIBRARY/'baseline-100.zip'),
                         ('model_source_sha256',ROOT/'app/radio_maps.py'),
                         ('script_sha256',ROOT/'scripts/build_learning_evidence.py')):
            self.assertEqual(self.learning[key],hashlib.sha256(path.read_bytes()).hexdigest())

    def test_displayed_scores_match_actual_refits_at_early_and_late_prefixes(self):
        field=next(f for f in self.learning['fields'] if f['name']=='district-a')
        mask=np.asarray(field['holdout_indices']);truth=np.asarray(field['reference_rssi_dbm'],dtype=float)
        for profile in self.learning['profiles']:
            for n in (field['counts'][0],field['counts'][-1]):
                frame=next(f for f in field['frames'] if f['profile']==profile['id'] and f['available_count']==n)
                model=RadioMap(profile['method'],field['scene']['tx']['position'],profile['noise_db']).fit(field['observations'][:n])
                mean,std=model.predict(field['reference_positions']);mean=np.asarray(mean)
                np.testing.assert_allclose(frame['mean_dbm'],mean,atol=.000501,rtol=0)
                self.assertAlmostEqual(frame['score']['mae_db'],np.abs(mean[mask]-truth[mask]).mean(),places=9)
                self.assertEqual(frame['training_indices'],model.training_indices)
                self.assertTrue(all(i<n for i in frame['training_indices']))


if __name__=='__main__':unittest.main()
