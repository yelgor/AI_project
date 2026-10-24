import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from app.radio import load_config, export_gazebo
from app.engine import RadioWorker as Radio


class RadioTests(unittest.TestCase):
    def test_upstream_free_space(self):
        radio=Radio({'transmitter':[0,0,2],'frequency_hz':2.4e9,'buildings':[]})
        result=radio.sample([10,0,2])
        expected=20+20*math.log10(299792458/2.4e9/(4*math.pi*10))
        self.assertAlmostEqual(result['rssi_dbm'],expected,places=3)
        self.assertEqual(result['path_count'],1)
        self.assertAlmostEqual(result['paths'][0]['delay_s'],10/299792458,places=12)

    def test_buildings_and_coherent_power(self):
        radio=Radio(load_config('config/world.json'))
        result=radio.sample([-10,10,1])
        self.assertGreater(result['path_count'],1)
        field=sum(complex(p['real'],p['imag']) for p in result['paths'])
        self.assertAlmostEqual(result['path_gain_linear'],abs(field)**2,places=12)
        self.assertTrue(all(p['delay_s']>0 for p in result['paths']))
        for bad in ([0,0,2],[float('nan'),0,1],[-10,0,2]):
            with self.assertRaises(ValueError): radio.sample(bad)

    def test_same_geometry_in_gazebo(self):
        config=load_config('config/world.json')
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'world.sdf'
            export_gazebo(config,file)
            models=ET.parse(file).findall('./world/model')
            self.assertEqual(len(models),len(config['buildings']))
            for model,b in zip(models,config['buildings']):
                self.assertEqual(list(map(float,model.find('pose').text.split()[:3])),b['center'])
                self.assertEqual(list(map(float,model.find('link/collision/geometry/box/size').text.split())),b['size'])


if __name__=='__main__': unittest.main()
