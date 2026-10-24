"""Portable experiment records: scene snapshot, manifest, JSONL, CSV and ZIP."""
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import threading
import uuid
import zipfile
from datetime import datetime, timezone

COLUMNS = ['dataset_id','sample_index','timestamp_utc','source','scene_revision','sim_time_s',
           'tx_x_m','tx_y_m','tx_z_m','rx_x_m','rx_y_m','rx_z_m',
           'rx_yaw_rad','rx_pitch_rad','rx_roll_rad','rssi_dbm','snr_db','path_gain_linear','path_count',
           'robot_x_m','robot_y_m','robot_z_m','robot_qx','robot_qy','robot_qz','robot_qw',
           'linear_x_mps','linear_y_mps','linear_z_mps','angular_x_radps','angular_y_radps','angular_z_radps']


def now(): return datetime.now(timezone.utc).isoformat()


def field_hash(scene):
    """RF field identity: robot spawn is not part of the Sionna geometry."""
    payload={k:scene[k] for k in ('objects','tx','radio')}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def atomic_json(path, value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    temp.replace(path)


class Dataset:
    def __init__(self, root, scene, revision, kind, parameters=None):
        self.lock=threading.RLock()
        self.id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        self.path=root/self.id; self.path.mkdir(parents=True)
        canonical=json.dumps(scene,sort_keys=True,separators=(',',':')).encode()
        versions={name:importlib.metadata.version(name) for name in ['sionna-rt','mitsuba','drjit','numpy']}
        self.manifest={'format_version':1,'dataset_id':self.id,'kind':kind,'status':'collecting',
                       'scene_revision':revision,'scene_sha256':hashlib.sha256(canonical).hexdigest(),
                       'radio_field_sha256':field_hash(scene),
                       'started_at':now(),'finished_at':None,'sample_count':0,'skipped_count':0,'error_count':0,
                       'parameters':parameters or {},'software':versions,'python':platform.python_version(),
                       'solver_runtime':{'drjit_merge_functions':True,'isolation':'process-per-scene'},
                       'platform':platform.platform(),'coordinate_frame':'world','length_unit':'m',
                       'angle_unit':'rad','power_unit':'dBm','time_unit':'s','velocity_frame':'base_link',
                       'limitations':['No packet-level PHY or latency model','Robot body is not part of radio geometry']}
        atomic_json(self.path/'scenario.json',scene)
        self.csvfile=open(self.path/'measurements.csv','w',newline='')
        self.csv=csv.DictWriter(self.csvfile,fieldnames=COLUMNS); self.csv.writeheader(); self.csvfile.flush()
        self.jsonfile=open(self.path/'measurements.jsonl','w')
        self.events=open(self.path/'events.jsonl','w')
        self.save()

    def save(self): atomic_json(self.path/'manifest.json',self.manifest)

    def append(self, result):
        with self.lock:
            if self.manifest['status']!='collecting': return
            index=self.manifest['sample_count']
            record={'dataset_id':self.id,'sample_index':index,'timestamp_utc':now(),**result}
            self.jsonfile.write(json.dumps(record,allow_nan=False)+'\n'); self.jsonfile.flush()
            row={k:record.get(k) for k in COLUMNS}
            for label,position in [('tx',record['tx_position_m']),('rx',record['position_m'])]:
                for axis,v in zip('xyz',position): row[f'{label}_{axis}_m']=v
            for label,v in zip(['yaw','pitch','roll'],record['orientation_rad']): row[f'rx_{label}_rad']=v
            if record.get('robot_pose'):
                pose=record['robot_pose']
                for axis,v in zip('xyz',pose['position']): row[f'robot_{axis}_m']=v
                for axis,v in zip('xyzw',pose['quaternion_xyzw']): row[f'robot_q{axis}']=v
                for label,key,unit in [('linear','linear_velocity','mps'),('angular','angular_velocity','radps')]:
                    for axis,v in zip('xyz',pose.get(key) or []): row[f'{label}_{axis}_{unit}']=v
            self.csv.writerow(row); self.csvfile.flush()
            self.manifest['sample_count']+=1; self.save()

    def event(self, kind, message, position=None):
        with self.lock:
            self.events.write(json.dumps({'timestamp_utc':now(),'kind':kind,'message':message,'position_m':position})+'\n')
            self.events.flush()
            if kind in ('skipped','error'):
                self.manifest['skipped_count' if kind=='skipped' else 'error_count']+=1
            self.save()

    def finish(self, status='completed'):
        with self.lock:
            if self.manifest['status']!='collecting': return
            self.manifest['status']=status; self.manifest['finished_at']=now()
            for f in (self.csvfile,self.jsonfile,self.events): f.close()
            self.save()


def list_datasets(root):
    return [json.loads(p.read_text()) for p in sorted(root.glob('*/manifest.json'),reverse=True)]


def completed_directory(root, identity):
    if not identity or any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity):
        raise ValueError('Invalid dataset id')
    directory=root/identity
    if not (directory/'manifest.json').is_file(): raise FileNotFoundError('Dataset not found')
    if json.loads((directory/'manifest.json').read_text())['status']=='collecting':
        raise ValueError('Stop recording or wait for grid completion before export')
    return directory


def read_dataset(root, identity):
    directory=completed_directory(root,identity)
    result={name:json.loads((directory/(name+'.json')).read_text()) for name in ('manifest','scenario')}
    result['manifest'].setdefault('radio_field_sha256',field_hash(result['scenario']))
    result['measurements']=[json.loads(line) for line in (directory/'measurements.jsonl').read_text().splitlines()]
    return result


def archive(root, identity):
    directory=completed_directory(root,identity)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('manifest.json','scenario.json','measurements.jsonl','measurements.csv','events.jsonl'):
            z.write(directory/name,arcname=identity+'/'+name)
    return buffer.getvalue()
