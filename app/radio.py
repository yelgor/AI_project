"""Integration with NVIDIA Sionna RT; propagation is computed by upstream."""
import argparse
import gc
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, HTTPServer
import xml.etree.ElementTree as ET
try:
    from .scenario import normalize, validate_position
except ImportError:
    from scenario import normalize, validate_position

os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parents[1]/'.cache/matplotlib'))
import mitsuba as mi
mi.set_variant('llvm_ad_mono_polarized')
import numpy as np
import drjit as dr
from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver, SceneObject, ITURadioMaterial

# Dr.Jit keeps native callable/JIT state beyond an individual scene. Keep its
# owner thread alive across Session replacements instead of recycling threads.
SOLVER_EXECUTOR = ThreadPoolExecutor(max_workers=1,thread_name_prefix='sionna')


def vector(value, label):
    if len(value) != 3 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError(f'{label} requires three finite coordinates')
    return [float(x) for x in value]


def load_config(path):
    data = json.loads(Path(path).read_text())
    if data.get('version') == 2: return normalize(data)
    data['transmitter'] = vector(data['transmitter'], 'transmitter')
    for b in data['buildings']:
        b['center'] = vector(b['center'], 'center')
        b['size'] = vector(b['size'], 'size')
        if min(b['size']) <= 0:
            raise ValueError('Building sizes must be positive')
    return data


def write_box(path, center, size, yaw_rad=0):
    # Geometry conversion only. Triangles are outward-facing.
    vertices = [(center[0]+x*size[0]/2, center[1]+y*size[1]/2, center[2]+z*size[2]/2)
                for x,y,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                              (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
    c,s=math.cos(yaw_rad),math.sin(yaw_rad)
    vertices=[(center[0]+c*(x-center[0])-s*(y-center[1]), center[1]+s*(x-center[0])+c*(y-center[1]), z) for x,y,z in vertices]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
             (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    lines = ['ply','format ascii 1.0','element vertex 8','property float x',
             'property float y','property float z','element face 12',
             'property list uchar int vertex_indices','end_header']
    lines += [' '.join(map(str,v)) for v in vertices]
    lines += ['3 '+' '.join(map(str,f)) for f in faces]
    path.write_text('\n'.join(lines)+'\n')


class Radio:
    def __init__(self, config):
        self.scenario = normalize(config)
        config = {'buildings':self.scenario['objects'], 'transmitter':self.scenario['tx']['position'], **self.scenario['radio']}
        self.config = config
        mi.set_variant('llvm_ad_mono_polarized')
        # Keep upstream callable deduplication enabled. Disabling it can crash
        # Dr.Jit 1.5 on a floor-only scene; scene isolation handles JIT lifetime.
        dr.set_flag(dr.JitFlag.MergeFunctions, True)
        self.scene = load_scene()
        self.scene.frequency = config.get('frequency_hz',2.4e9)
        self.scene.tx_array = PlanarArray(num_rows=1,num_cols=1,vertical_spacing=.5,
                                         horizontal_spacing=.5,pattern='iso',polarization='V')
        self.scene.rx_array = self.scene.tx_array
        with TemporaryDirectory() as temporary:
            for i,b in enumerate(config['buildings']):
                path = Path(temporary)/f'{i}.ply'
                write_box(path,b['center'],b['size'],b.get('yaw_rad',0))
                material = ITURadioMaterial(name=f'material_{i}',itu_type=b.get('material','concrete'),
                                            thickness=b.get('thickness_m',.2))
                self.scene.add(SceneObject(name=f'building_{i}',fname=str(path),radio_material=material))
        self.scene.add(Transmitter(name='base',position=config['transmitter'],orientation=self.scenario['tx']['orientation_rad']))
        self.receiver = Receiver(name='robot',position=[-10,10,1])
        self.scene.add(self.receiver)
        self.solver = PathSolver()

    def close(self):
        """Release native scene objects on the same thread that created them."""
        mi.set_variant('llvm_ad_mono_polarized')
        dr.sync_thread()
        self.solver=None; self.receiver=None; self.scene=None
        gc.collect()
        # Native callables can outlive a destroyed scene in Dr.Jit's kernel
        # cache. Do not reuse those compiled dispatch tables for a new scene.
        dr.flush_kernel_cache()

    def sample(self, position, orientation_rad=None):
        mi.set_variant('llvm_ad_mono_polarized')
        dr.set_flag(dr.JitFlag.MergeFunctions, True)
        position = vector(position,'receiver')
        if math.dist(position,self.config['transmitter']) < .1:
            raise ValueError('Receiver must be at least 0.1m from transmitter')
        validate_position(self.scenario,position)
        self.receiver.position = position
        self.receiver.orientation = orientation_rad or self.scenario['rx']['orientation_rad']
        settings = self.config.get('solver',{})
        paths = self.solver(self.scene,max_depth=settings.get('max_depth',3),
                            samples_per_src=settings.get('samples_per_src',10000),
                            max_num_paths_per_src=settings.get('max_num_paths_per_src',10000),
                            specular_reflection=True,refraction=True,diffraction=True,
                            edge_diffraction=True,seed=settings.get('seed',42))
        a,tau = paths.cir(normalize_delays=False,out_type='numpy')
        coefficients = np.asarray(a).reshape(-1)
        delays = np.asarray(tau).reshape(-1)
        active = np.abs(coefficients)>0
        coefficients = coefficients[active]
        delays = delays[active]
        # Narrowband power is the coherent sum; a contains carrier phases.
        gain = float(abs(np.sum(coefficients))**2)
        rssi = self.config.get('tx_power_dbm',20)+10*math.log10(gain) if gain>0 else None
        noise = -174+10*math.log10(self.config.get('bandwidth_hz',20e6))+self.config.get('noise_figure_db',5)
        return {'position_m':position,'rssi_dbm':rssi,'snr_db':rssi-noise if rssi is not None else None,
                'path_gain_linear':gain,'path_count':len(coefficients),
                'paths':[{'real':float(c.real),'imag':float(c.imag),'delay_s':float(t)}
                         for c,t in zip(coefficients,delays)]}


def export_gazebo(config, destination):
    scenario=normalize(config)
    config={'buildings':scenario['objects']}
    root=ET.Element('sdf',version='1.9')
    world=ET.SubElement(root,'world',name='radio_world')
    for filename,name in [('gz-sim-physics-system','gz::sim::systems::Physics'),
                          ('gz-sim-user-commands-system','gz::sim::systems::UserCommands'),
                          ('gz-sim-scene-broadcaster-system','gz::sim::systems::SceneBroadcaster')]:
        ET.SubElement(world,'plugin',filename=filename,name=name)
    for i,b in enumerate(config['buildings']):
        model=ET.SubElement(world,'model',name=f'building_{i}')
        ET.SubElement(model,'static').text='true'
        ET.SubElement(model,'pose').text=' '.join(map(str,b['center']))+f' 0 0 {b.get("yaw_rad",0)}'
        link=ET.SubElement(model,'link',name='body')
        for kind in ('collision','visual'):
            geometry=ET.SubElement(ET.SubElement(link,kind,name=kind),'geometry')
            ET.SubElement(ET.SubElement(geometry,'box'),'size').text=' '.join(map(str,b['size']))
    light=ET.SubElement(world,'light',name='sun',type='directional')
    ET.SubElement(light,'pose').text='0 0 10 0 0 0'
    ET.SubElement(light,'direction').text='-0.5 0.1 -0.9'
    ET.ElementTree(root).write(destination,encoding='unicode',xml_declaration=True)


def serve(radio, host, port):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self,status,data):
            body=json.dumps(data,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self.send_json(200,{'status':'ok','backend':'Sionna RT CPU'}) if self.path=='/health' else self.send_json(404,{'error':'Not found'})
        def do_POST(self):
            if self.path!='/sample':
                self.send_json(404,{'error':'Not found'})
                return
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=4096: raise ValueError('Body size must be 1..4096 bytes')
                request=json.loads(self.rfile.read(n))
                self.send_json(200,radio.sample(request['position_m']))
            except (ValueError,KeyError,TypeError) as e:
                self.send_json(400,{'error':str(e)})
    # Single-threaded: Mitsuba scene mutation and solver are serialized.
    HTTPServer((host,port),Handler).serve_forever()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='config/world.json')
    sub=parser.add_subparsers(dest='command',required=True)
    sample=sub.add_parser('sample'); sample.add_argument('position',nargs=3,type=float)
    trajectory=sub.add_parser('trajectory'); trajectory.add_argument('input'); trajectory.add_argument('output')
    server=sub.add_parser('serve'); server.add_argument('--host',default='127.0.0.1'); server.add_argument('--port',type=int,default=8000)
    coverage=sub.add_parser('map'); coverage.add_argument('output'); coverage.add_argument('--bounds',nargs=4,type=float,default=[-15,-15,15,15]); coverage.add_argument('--step',type=float,default=5)
    export=sub.add_parser('export-gazebo'); export.add_argument('output')
    args=parser.parse_args(); config=load_config(args.config)
    if args.command=='export-gazebo': export_gazebo(config,args.output); return
    radio=Radio(config)
    config=radio.config
    if args.command=='sample': print(json.dumps(radio.sample(args.position),indent=2,allow_nan=False))
    elif args.command=='trajectory':
        points=json.loads(Path(args.input).read_text())
        with open(args.output,'w') as file:
            for i,p in enumerate(points):
                file.write(json.dumps({'index':i,**radio.sample(p)},allow_nan=False)+'\n')
    elif args.command=='map':
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        xmin,ymin,xmax,ymax=args.bounds
        if not all(math.isfinite(v) for v in args.bounds) or not math.isfinite(args.step) or args.step<=0 or xmax<=xmin or ymax<=ymin:
            raise ValueError('Ordered finite bounds and positive step required')
        if ((xmax-xmin)/args.step+1)*((ymax-ymin)/args.step+1)>2500:
            raise ValueError('Map limited to 2500 positions; increase --step')
        points=[]; levels=[]
        for y in np.arange(ymin,ymax+args.step*.001,args.step):
            for x in np.arange(xmin,xmax+args.step*.001,args.step):
                try: result=radio.sample([float(x),float(y),1])
                except ValueError: continue
                if result['rssi_dbm'] is not None:
                    points.append([x,y]); levels.append(result['rssi_dbm'])
        if not points: raise ValueError('No valid radio samples in selected map')
        fig,ax=plt.subplots()
        pts=np.asarray(points)
        plotted=ax.scatter(pts[:,0],pts[:,1],c=levels,cmap='viridis',s=100,marker='s')
        for b in config['buildings']:
            if b['center'][2]+b['size'][2]/2<=0: continue
            ax.add_patch(Rectangle((b['center'][0]-b['size'][0]/2,b['center'][1]-b['size'][1]/2),*b['size'][:2],angle=math.degrees(b.get('yaw_rad',0)),rotation_point='center',facecolor='gray',alpha=.7))
        ax.scatter(*config['transmitter'][:2],marker='*',s=150,c='red',label='Transmitter')
        fig.colorbar(plotted,ax=ax,label='RSSI (dBm)')
        ax.set(xlabel='x (m)',ylabel='y (m)',title='Sionna RT, receiver height 1m',aspect='equal')
        ax.legend(); fig.savefig(args.output,dpi=160,bbox_inches='tight'); plt.close(fig)
        print(f'Saved {len(points)} computed radio samples to {args.output}')
    else: serve(radio,args.host,args.port)


if __name__=='__main__': main()
