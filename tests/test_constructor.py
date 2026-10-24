import csv
import io
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from app.scenario import normalize, preset, inside, antenna_pose, quat_from_ypr
from app.radio import write_box, export_gazebo
from app.engine import RadioWorker as Radio
from app.builder import Session
from app.datasets import archive
import xml.etree.ElementTree as ET


class GeometryTests(unittest.TestCase):
    def test_room_is_hollow_and_door_is_open(self):
        scene=preset()
        self.assertFalse(any(inside(o,[0,0,1]) for o in scene['objects']))
        self.assertFalse(any(inside(o,[0,-4,1]) for o in scene['objects']))
        self.assertTrue(any(inside(o,[2,-4,1]) for o in scene['objects']))
        Radio(scene).sample([0,0,1])

    def test_rotated_mesh_matches_sdf(self):
        obj={'id':'wall','label':'wall','center':[2,3,1],'size':[4,.2,2],
             'yaw_rad':math.pi/2,'material':'concrete','thickness_m':.2}
        scene=preset('empty'); scene['rx']['position']=[-2,2,1]; scene['objects'].append(obj)
        self.assertTrue(inside(obj,[2,4,1])); self.assertFalse(inside(obj,[3,3,1]))
        with tempfile.TemporaryDirectory() as directory:
            mesh=Path(directory)/'wall.ply'; sdf=Path(directory)/'world.sdf'
            write_box(mesh,obj['center'],obj['size'],obj['yaw_rad'])
            lines=mesh.read_text().split('end_header\n')[1].splitlines()
            vertices=[list(map(float,line.split())) for line in lines[:8]]
            self.assertAlmostEqual(max(v[0] for v in vertices)-min(v[0] for v in vertices),.2)
            self.assertAlmostEqual(max(v[1] for v in vertices)-min(v[1] for v in vertices),4)
            export_gazebo(scene,sdf)
            self.assertAlmostEqual(float(ET.parse(sdf).findall('./world/model')[-1].find('pose').text.split()[-1]),math.pi/2)

    def test_antenna_rigid_transform_includes_z_and_rotation(self):
        scene=preset(); scene['rx']['mount_position']=[1,0,.7]
        position,angles=antenna_pose(scene,{'position':[3,4,.2],'quaternion_xyzw':quat_from_ypr([math.pi/2,0,0])})
        for actual,expected in zip(position,[3,5,.9]): self.assertAlmostEqual(actual,expected)
        self.assertAlmostEqual(angles[0],math.pi/2)
        position,_=antenna_pose(scene,{'position':[3,4,.2],'quaternion_xyzw':quat_from_ypr([0,math.pi/2,0])})
        self.assertAlmostEqual(position[0],3.7); self.assertAlmostEqual(position[2],-.8)

    def test_invalid_scene_and_legacy_migration(self):
        bad=preset(); bad['objects'][1]['size'][0]=-1
        with self.assertRaises(ValueError): normalize(bad)
        bad=preset(); bad['tx']['position']=[float('nan'),0,1]
        with self.assertRaises(ValueError): normalize(bad)
        migrated=normalize(json.loads(Path('config/world.json').read_text()))
        self.assertEqual(migrated['version'],2)
        self.assertEqual(migrated['tx']['position'],[-10,0,2])


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.session=Session(self.temp.name)
    def tearDown(self):
        self.session.close(); self.temp.cleanup()

    def test_record_snapshot_csv_cir_and_zip(self):
        scene=preset('empty'); scene['rx']['position']=[2,2,2]
        self.session.apply(scene)
        manifest=self.session.begin_record()
        self.session.sample(); self.session.end_record()
        package=archive(self.session.data,manifest['dataset_id'])
        with zipfile.ZipFile(io.BytesIO(package)) as z:
            prefix=manifest['dataset_id']+'/'
            saved=json.loads(z.read(prefix+'scenario.json'))
            rows=list(csv.DictReader(io.StringIO(z.read(prefix+'measurements.csv').decode())))
            records=[json.loads(line) for line in z.read(prefix+'measurements.jsonl').decode().splitlines()]
            info=json.loads(z.read(prefix+'manifest.json'))
            self.assertEqual(saved,scene)
            self.assertEqual(info['status'],'completed')
            self.assertGreaterEqual(info['sample_count'],1)
            self.assertEqual(len(rows),len(records))
            self.assertEqual(float(rows[0]['rx_z_m']),2)
            self.assertTrue(records[0]['paths'])
            self.assertEqual(records[0]['scene_revision'],info['scene_revision'])

    def test_grid_multiple_heights_and_apply_guard(self):
        job=self.session.grid({'min':[-1,0,1],'max':[1,0,2],'step':[1,1,1]})
        with self.assertRaises(ValueError): self.session.apply(preset('empty'))
        deadline=time.monotonic()+45
        while self.session.job['status']=='running' and time.monotonic()<deadline: time.sleep(.1)
        self.assertEqual(self.session.job['status'],'completed')
        manifest=json.loads((self.session.data/job['dataset_id']/'manifest.json').read_text())
        self.assertEqual(manifest['sample_count'],6)
        rows=[json.loads(line) for line in (self.session.data/job['dataset_id']/'measurements.jsonl').read_text().splitlines()]
        self.assertEqual({row['position_m'][2] for row in rows},{1,2})


if __name__=='__main__': unittest.main()
