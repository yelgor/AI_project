"""Mission quality gates, scheduling and stale-telemetry regression checks."""
import copy
import math
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.campaigns import schedule
from app.missions import mission,line_of_sight
from app.navigation import free
from app.builder import Session
from app.experiments import Experiments
from test_experiments import FakeSession


class MissionTests(unittest.TestCase):
    def test_physical_routes_and_obstacle_shadow_all_families(self):
        for name in ('shadow','office','warehouse','district','courtyard'):
            for layout in (0,1):
                spec=mission(name,layout);s=spec['scene']
                self.assertEqual(s['rx']['mode'],'husky')
                self.assertTrue(spec['config']['require_shadow_loss'])
                previous=s['robot']['position'][:2]
                for waypoint in spec['config']['route']:
                    for j in range(101):
                        x,y=[previous[k]+(waypoint[k]-previous[k])*j/100 for k in (0,1)]
                        self.assertTrue(free(s,x,y,.56),(name,layout,x,y))
                    previous=waypoint[:2]
                self.assertTrue(line_of_sight(s,[-4,3.5,.83]))
                self.assertFalse(line_of_sight(s,[4,0,.83]))
                self.assertEqual(s['rx']['mount_position'],[0,0,.7])

    def test_full_factorial_schedule_and_family_split(self):
        tasks,workers=schedule({'runs':140,'workers':2,'methods':['B0','B1','IDW','GPR-zero','GPR-pathloss'],'betas':[0,1],'protocol':'paired'})
        self.assertEqual((len(tasks),workers),(140,2))
        self.assertEqual({t['index'] for t in tasks},set(range(140)))
        for repeat in (0,1):
            subset=[t for t in tasks if t['repeat']==repeat]
            self.assertEqual(len(subset),70)
            self.assertEqual(len({(t['trial']['name'],t['method'],t['beta']) for t in subset}),70)
        self.assertEqual({t['trial']['world'] for t in tasks if t['trial']['split']=='test'},{'courtyard'})
        self.assertTrue(all(t['beta']==0 for t in tasks if t['method'] in ('B0','B1','IDW')))
        self.assertTrue(all(not t['trial']['config']['save_cir'] for t in tasks))
        for invalid in ({'runs':0},{'workers':5},{'protocol':'fake'},{'methods':['made-up']}):
            with self.assertRaises(ValueError):schedule(invalid)

    def test_old_reset_epoch_and_clock_are_rejected(self):
        # Exercise the actual ingress guard without starting solver/Gazebo processes.
        s=Session.__new__(Session);s.lock=threading.RLock();s.robot_epoch=4
        s.minimum_pose_time=10;s.revision='new';s.robot_status='running';s.experiments=None;s.measurement=None
        payload={'position':[0,0,.13],'quaternion_xyzw':[0,0,0,1],
                 'sim_time_s':11,'robot_epoch':4,'scene_revision':'new'}
        for changed in ({'robot_epoch':3},{'sim_time_s':9},{'scene_revision':'old'}):
            with self.assertRaises(ValueError):s.telemetry({**payload,**changed})
        s.telemetry(payload)
        self.assertEqual(s.pose['sim_time_s'],11)

    def test_los_loss_is_invalid_and_shadow_loss_is_accepted(self):
        for visible in (True,False):
            with tempfile.TemporaryDirectory() as tmp:
                session=FakeSession(tmp);exp=Experiments(session,start_worker=False)
                exp.start({'method':'B1','degraded_s':0,'require_shadow_loss':True})
                for t,rssi in ((0,-35),(1,-60)):
                    session.current['sim_time_s']=t
                    exp.pose(copy.deepcopy(session.current),{'ready':True,'status':'running'})
                    exp.observe({'source':'husky','scene_revision':'test','sim_time_s':t,
                        'position_m':[t,0,.83],'rssi_dbm':rssi,'robot_pose':copy.deepcopy(session.current),
                        'line_of_sight':visible})
                    if t and visible:
                        with self.assertRaisesRegex(ValueError,'before the obstacle'):exp.step()
                    else:exp.step()
                if not visible:self.assertEqual(exp.state()['mode'],'RECOVERY')
                exp.close()


if __name__=='__main__':unittest.main()
