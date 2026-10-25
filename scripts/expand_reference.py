"""Collect independent multi-height Sionna reference grids for campaign fields.

Never connects to the live controller. Output datasets are evaluation-only.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.datasets import Dataset,archive,field_hash,atomic_json
from app.engine import RadioWorker
from app.missions import line_of_sight
from app.navigation import free
from app.provenance import implementation_hash
from app.campaigns import schedule


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign',type=Path)
    parser.add_argument('--step',type=float,default=1.)
    parser.add_argument('--heights',type=float,nargs='+',default=[.83228,1.2,1.8])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not .25<=args.step<=3 or any(not .3<=z<=3 for z in args.heights):parser.error('step .25..3m; heights .3..3m')
    os.environ.setdefault('RADIO_THREADS','1')
    output=args.output or args.campaign/'reference';output.mkdir(parents=True,exist_ok=True)
    staging=tempfile.TemporaryDirectory(prefix='radio-reference-')
    data=Path(staging.name);index=[]
    sources=json.loads((args.campaign/'sources.json').read_text())
    tasks,_=schedule(json.loads((args.campaign/'manifest.json').read_text())['config'])
    for name,source in sources.items():
        package=output/(name+'.zip')
        if package.exists():
            import zipfile
            with zipfile.ZipFile(package) as z:
                meta=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/manifest.json'))))
            if (meta['radio_field_sha256']!=field_hash(source['scene']) or
                meta['parameters'].get('step_m')!=args.step or meta['parameters'].get('heights_m')!=args.heights):
                raise ValueError('Existing reference settings differ; choose a new --output directory')
            index.append({'scene':name,'file':package.name,'dataset_id':meta['dataset_id'],
                          'count':meta['sample_count'],'radio_field_sha256':meta['radio_field_sha256']});continue
        scene=source['scene'];bounds=next(t['trial']['config']['bounds'] for t in tasks if t['trial']['name']==name)
        x0,y0,x1,y1=bounds
        points=[[x0+ix*args.step,y0+iy*args.step,z] for z in args.heights
                for iy in range(int((y1-y0)/args.step)+1) for ix in range(int((x1-x0)/args.step)+1)
                if free(scene,x0+ix*args.step,y0+iy*args.step,.56)]
        dataset=Dataset(data,scene,field_hash(scene)[:12],'grid',{'bounds':bounds,'step_m':args.step,
            'heights_m':args.heights,'planned_count':len(points),'evaluation_only':True,'controller_training':False})
        dataset.manifest['implementation_sha256']=implementation_hash()
        worker=RadioWorker(scene)
        try:
            for i,point in enumerate(points):
                result=worker.sample(point,include_paths=False)
                result.update(source='grid',scene_revision=dataset.manifest['scene_revision'],sim_time_s=None,
                    tx_position_m=scene['tx']['position'],orientation_rad=[0,0,0],robot_pose=None,
                    line_of_sight=line_of_sight(scene,point))
                dataset.append(result)
            dataset.finish();package.write_bytes(archive(data,dataset.id))
            index.append({'scene':name,'file':package.name,'dataset_id':dataset.id,'count':len(points),
                          'radio_field_sha256':field_hash(scene)})
            print(name,len(points),'independent reference positions',flush=True)
            atomic_json(output/'index.json',{'evaluation_only':True,'fields':index,'total_points':sum(r['count'] for r in index)})
        except BaseException:
            dataset.finish('interrupted');raise
        finally:worker.close()
    atomic_json(output/'index.json',{'evaluation_only':True,'fields':index,'total_points':sum(r['count'] for r in index)})
    staging.cleanup()


if __name__=='__main__':main()
