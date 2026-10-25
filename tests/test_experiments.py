import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import io
import numpy as np
from app.navigation import free, export_map
from app.scenario import preset, normalize
from app.radio_maps import RadioMap
from app.experiments import Experiments, configuration, select_target


class MapTests(unittest.TestCase):
    def test_all_worlds_and_door_clearance(self):
        for name in ('empty','room','corridor','warehouse','courtyard'):
            scene=preset(name)
            self.assertTrue(free(scene,*scene['robot']['position'][:2],.55),name)
        room=preset('room')
        self.assertTrue(free(room,0,-4,.55))
        self.assertFalse(free(room,.4,-4,.55))
        self.assertFalse(free(room,2,4))
        with tempfile.TemporaryDirectory() as directory:
            meta=export_map(room,directory,.2)
            self.assertEqual(meta['width'],150)
            self.assertTrue((Path(directory)/'map.pgm').read_bytes().startswith(b'P5\n150 150\n255\n'))

    def test_idw_exact_and_gpr_uncertainty(self):
        observations=[{'position_m':[0,0,1],'rssi_dbm':-30.}, {'position_m':[1,0,1],'rssi_dbm':-40.}]
        idw=RadioMap('IDW',[-2,0,1]).fit(observations)
        mean,std=idw.predict([[0,0,1],[.5,0,1]])
        self.assertAlmostEqual(mean[0],-30);self.assertAlmostEqual(mean[1],-35);self.assertEqual(std,[None,None])
        for method in ('GPR-zero','GPR-pathloss'):
            gp=RadioMap(method,[-2,0,1]).fit(observations)
            mean,std=gp.predict([[0,0,1],[10,0,1]])
            self.assertLess(abs(mean[0]+30),1.)
            self.assertGreater(std[1],std[0]*3)
        with self.assertRaises(ValueError): configuration({'method':'IDW','beta':1})

    def test_vectorized_spatial_thinning_preserves_capped_training_set(self):
        rng=np.random.default_rng(42)
        observations=[{'position_m':p.tolist(),'rssi_dbm':-40.} for p in rng.normal(size=(250,3))]
        observations+=observations[-20:]
        old=[]
        for i in reversed(range(len(observations))):
            if any(np.linalg.norm(np.asarray(observations[i]['position_m'])-observations[j]['position_m'])<.15 for j in old):continue
            old.append(i)
            if len(old)>=150:break
        model=RadioMap('IDW',[0,0,1]).fit(observations)
        self.assertEqual(model.training_indices,sorted(old))

    def test_route_distance_and_unreachable_candidates(self):
        candidates=[{'base':[1,0,0]},{'base':[0,2,0]},{'base':[0,3,0]}]
        def plan(point):
            if point[0]==1: raise ValueError('Wall')
            return {'path':[[0,0],point[:2]],'length_m':3 if point[1]==2 else 4}
        self.assertEqual(select_target(candidates,[0,0],plan)['base'],[0,2,0])
        with self.assertRaises(ValueError): select_target(candidates[:1],[0,0],plan)
        def unavailable(point):raise RuntimeError('Planner unavailable')
        with self.assertRaises(RuntimeError):select_target(candidates,[0,0],unavailable)

    def test_beta_rejects_uncertain_safe_mean(self):
        cells=[{'base':[1,0,0],'mean':-35.,'std':8.},{'base':[2,0,0],'mean':-36.,'std':1.}]
        def select(beta):
            safe=[c for c in cells if c['mean']-beta*c['std']>=-40]
            return select_target(safe,[0,0],lambda p:{'path':[],'length_m':math.hypot(*p[:2])})['base']
        self.assertEqual(select(0),[1,0,0]); self.assertEqual(select(1),[2,0,0])


class FakeSession:
    def __init__(self,root):
        self.root=Path(root);self.scene=preset('empty');self.scene['rx']['mode']='husky';self.calls=[]
        self.current={'position':[0,0,.13],'quaternion_xyzw':[0,0,0,1],'sim_time_s':0.}
    def state(self):
        return {'robot_status':'running','scenario':self.scene,'recording':None,'job':None,
                'navigation':{'ready':True,'status':'idle'},'revision':'test','robot_pose':copy.deepcopy(self.current)}
    def runtime(self,route,data):
        self.calls.append((route,data))
        if route=='/nav/plan': return {'length_m':math.dist(self.current['position'][:2],data['position'][:2]),'path':[[0,0],data['position'][:2]]}
        return {'status':'running' if route=='/nav/goal' else 'idle','ready':True}
    def check_shadow(self,config):return {'goal':config['shadow_goal'],'controller_training':False}


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.session=FakeSession(self.temp.name)
        self.exp=Experiments(self.session,start_worker=False)
    def tearDown(self):
        self.exp.close();self.temp.cleanup()
    def observation(self,t,x,rssi,measured_at=None):
        pose={'position':[x,0,.13],'quaternion_xyzw':[0,0,0,1],'sim_time_s':t}
        self.session.current=pose;self.exp.pose(pose,{'ready':True,'status':'running'})
        self.exp.observe({'source':'husky','scene_revision':'test','sim_time_s':t if measured_at is None else measured_at,
            'position_m':[x,0,.83],'rssi_dbm':rssi,'robot_pose':pose,'paths':[]})
        self.exp.step()

    def test_recovery_hysteresis_causal_replay_and_archive(self):
        meta=self.exp.start({'method':'B1','degraded_s':1,'stable_s':1})
        self.observation(0,0,-35)
        self.observation(1,1,-43)
        self.assertEqual(self.exp.state()['mode'],'TELEOP')
        self.observation(2,2,-44)
        self.assertEqual(self.exp.state()['mode'],'RECOVERY')
        self.assertTrue(any(route=='/nav/goal' for route,_ in self.session.calls))
        self.observation(3,0,-35,measured_at=2.5)
        self.observation(4,0,-35)
        self.assertEqual(self.exp.state()['mode'],'RECOVERED_WAIT')
        replay=self.exp.replay(meta['experiment_id'])
        cutoff=replay['timeline'][3]['sequence']
        self.assertEqual(self.exp.replay(meta['experiment_id'],cutoff)['timeline'],replay['timeline'][4:])
        self.assertEqual(self.exp.replay(meta['experiment_id'],replay['timeline'][-1]['sequence'])['timeline'],[])
        late=[e for e in replay['timeline'] if e['kind']=='observation' and e['measurement']['sim_time_s']==2.5][0]
        self.assertEqual(late['sim_time_s'],3)
        self.assertNotIn(late,[e for e in replay['timeline'] if e['sim_time_s']<=2.5])
        self.assertEqual(replay['manifest']['metrics']['observation_count'],5)
        for e in replay['timeline']:
            if e['kind']=='map':
                self.assertLessEqual(e['observation_count'],sum(o['kind']=='observation' and o['sequence']<e['sequence'] for o in replay['timeline']))
        with zipfile.ZipFile(io.BytesIO(self.exp.archive(meta['experiment_id']))) as package:
            self.assertIn(meta['experiment_id']+'/timeline.jsonl',package.namelist())

    def test_missing_safe_history_and_restart(self):
        meta=self.exp.start({'method':'B0','degraded_s':0})
        with self.assertRaisesRegex(ValueError,'No reachable safe target'): self.observation(0,0,None)
        with self.assertRaises(ValueError): self.exp.archive(meta['experiment_id'])
        # Simulate process death: the previous writer no longer owns this run.
        self.exp.run=None
        recovered=Experiments(self.session,start_worker=False)
        self.assertEqual(recovered.manifests()[0]['status'],'INTERRUPTED')
        recovered.close()

    def test_configuration_rejects_invalid_and_large_grid(self):
        for data in ({'bounds':[1,1,0,0]},{'beta':float('nan')},{'bounds':[-100,-100,100,100],'grid_step_m':.3}):
            with self.assertRaises(ValueError):configuration(data)

    def test_stop_still_stops_motion_if_logging_fails(self):
        self.exp.start({'method':'B1'})
        with patch.object(self.exp,'event',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.exp.stop()
        self.assertEqual(self.session.calls[-1][0],'/nav/hold')
        self.assertFalse(self.exp.active())

    def test_paired_history_excludes_post_loss_observations(self):
        source=self.exp.start({'method':'B1','degraded_s':0})
        self.observation(0,0,-35)
        self.observation(1,1,-50)
        self.observation(2,2,-36)
        self.exp.finish('CANCELLED','Test source complete')
        self.session.current={'position':[1,0,.13],'quaternion_xyzw':[0,0,0,1],'sim_time_s':0.}
        self.exp.start({'method':'B1','history_from':source['experiment_id']})
        self.assertEqual([o['rssi_dbm'] for o in self.exp.run['observations']],[-35,-50])
        self.assertTrue(all(o['available_at_sim_time_s']==0 for o in self.exp.run['observations']))
        self.assertTrue(all(o['sim_time_s']<=0 for o in self.exp.run['observations']))
        self.assertEqual(self.exp.state()['mode'],'LINK_DEGRADED')
        self.exp.observe({'source':'husky','scene_revision':'test','sim_time_s':.5,
            'position_m':[1,0,.83],'rssi_dbm':-38,'robot_pose':self.session.current})
        self.exp.step()
        self.assertEqual(self.exp.run['map']['observation_count'],2)
        self.exp.step()
        self.assertEqual(self.exp.run['map']['observation_count'],3)
        self.exp.finish('CANCELLED','Test complete')
        self.session.scene['tx']['position'][0]+=1
        with self.assertRaisesRegex(ValueError,'different RF field'):
            self.exp.start({'method':'B1','history_from':source['experiment_id']})

    def test_paired_monitor_uses_physical_time_instead_of_bulk_seed_arrival(self):
        source=self.exp.start({'method':'B1','degraded_s':0,'monitor_window_s':2})
        self.observation(0,0,-10)
        self.observation(4,1,-60)
        self.exp.finish('CANCELLED','Source collected')
        self.session.current={'position':[1,0,.13],'quaternion_xyzw':[0,0,0,1],'sim_time_s':10.}
        self.exp.start({'method':'B1','history_from':source['experiment_id'],'monitor_window_s':2})
        self.observation(10.5,1,-60)
        self.assertLess(self.exp.run['observations'][-1]['monitor_rssi_dbm'],-59)
        self.assertNotEqual(self.exp.state()['mode'],'RECOVERED_WAIT')

    def responsive(self,**extra):
        return self.exp.start({'method':'B1','loss_policy':'responsive','q_safe_dbm':-47,
            'hysteresis_db':1,'degraded_s':.5,'stable_s':.5,'stale_s':1.5,**extra})

    def responsive_sample(self,t,rssi,x=0,speed=0):
        pose={'position':[x,0,.13],'quaternion_xyzw':[0,0,0,1],'sim_time_s':t,
              'linear_velocity':[speed,0,0],'angular_velocity':[0,0,0]}
        self.session.current=pose;self.exp.pose(pose,{'ready':True,'status':'running'})
        self.exp.observe({'source':'husky','scene_revision':'test','sim_time_s':t,
            'position_m':[x,0,.83],'rssi_dbm':rssi,'robot_pose':pose,'line_of_sight':False})
        self.exp.step()

    def test_responsive_brakes_before_confirmation_and_does_not_wait_for_far_anchor(self):
        self.responsive(shadow_goal=[20,0]);self.responsive_sample(0,-35)
        self.responsive_sample(.25,-49,.1,.4)
        self.assertEqual(self.exp.state()['mode'],'LINK_SUSPECT')
        self.assertTrue(any(route=='/nav/hold' for route,_ in self.session.calls))
        self.responsive_sample(.5,-50,.14,.1);self.responsive_sample(.75,-51,.16,.06)
        self.assertEqual(self.exp.state()['mode'],'LINK_DEGRADED')
        self.assertFalse(any(route=='/nav/goal' for route,_ in self.session.calls))
        self.responsive_sample(1,-51,.17,0);self.responsive_sample(1.25,-51,.17,0)
        self.assertEqual(self.exp.state()['mode'],'RECOVERY')
        self.assertAlmostEqual(self.exp.run['brake_distance_m'],.07)
        events=self.exp.replay(self.exp.state()['experiment_id'])['timeline']
        self.assertLess(next(e['sequence'] for e in events if e['kind']=='brake'),next(e['sequence'] for e in events if e['kind']=='target'))

    def test_single_dip_waits_for_stable_recovery_then_resumes_without_return(self):
        self.responsive();self.responsive_sample(0,-35);self.responsive_sample(.25,-49)
        self.responsive_sample(.5,-35);self.responsive_sample(.75,-35)
        self.assertEqual(self.exp.state()['mode'],'LINK_SUSPECT')
        self.responsive_sample(1,-35)
        self.assertEqual(self.exp.state()['mode'],'TELEOP')
        self.assertFalse(any(route=='/nav/goal' for route,_ in self.session.calls))

    def test_borderline_link_cannot_wait_in_suspect_state_until_global_timeout(self):
        self.responsive();self.responsive_sample(0,-35);self.responsive_sample(.25,-49)
        for t in (.5,.75,1,1.25,1.5,1.75,2):self.responsive_sample(t,-47.5)
        self.assertEqual(self.exp.state()['mode'],'LINK_SUSPECT')
        self.responsive_sample(2.25,-47.5)
        self.assertEqual(self.exp.state()['mode'],'RECOVERY')
        self.assertEqual(self.exp.run['loss_decision'],'verification_timeout')

    def test_duplicates_do_not_confirm_loss_and_missing_speeds_do_not_allow_recovery(self):
        self.responsive();self.responsive_sample(0,-35);self.responsive_sample(.25,-49)
        count=len(self.exp.run['observations'])
        self.responsive_sample(.25,-49);self.assertEqual(len(self.exp.run['observations']),count)
        self.responsive_sample(.75,-49,speed=.1)
        self.exp.run['pose'].pop('linear_velocity');self.exp.run['quiet_since']=None;self.exp.step()
        self.assertEqual(self.exp.state()['mode'],'LINK_DEGRADED')
        self.assertFalse(any(route=='/nav/goal' for route,_ in self.session.calls))

    def test_excess_motion_without_new_reading_and_solver_errors_stop(self):
        self.responsive();self.responsive_sample(0,-35)
        pose={**self.session.current,'sim_time_s':.5,'position':[.6,0,.13]}
        self.exp.pose(pose,{'ready':True,'status':'running'})
        with self.assertRaisesRegex(ValueError,'distance allowed'):self.exp.step()
        self.session.error='Native solver failed'
        with patch('app.experiments.time.sleep',side_effect=lambda _:setattr(self.exp,'closed',True)):
            self.exp.loop()
        self.assertEqual(self.exp.state()['status'],'FAILED')
        self.assertEqual(self.session.calls[-1][0],'/nav/hold')

    def test_invalid_rssi_is_rejected_without_becoming_a_fake_loss(self):
        self.responsive();self.responsive_sample(0,-35)
        with self.assertRaisesRegex(ValueError,'Invalid RSSI'):
            self.exp.observe({'source':'husky','scene_revision':'test','sim_time_s':.25,
                'position_m':[0,0,.83],'rssi_dbm':float('nan')})
        self.assertEqual(len(self.exp.run['observations']),1)
        self.assertEqual(self.exp.state()['mode'],'TELEOP')


if __name__=='__main__':unittest.main()
