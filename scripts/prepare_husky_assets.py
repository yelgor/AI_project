"""Extract licensed official Clearpath visual meshes and URDF transforms for web view.

Run inside the ROS/Clearpath container; no replacement robot physics is generated.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.scenario import quat_from_ypr, quat_multiply, rotate
from ament_index_python.packages import get_package_share_directory

root=Path(__file__).resolve().parents[1]
output=root/'.runtime/assets/husky'; output.mkdir(parents=True,exist_ok=True)
setup=Path('/tmp/clearpath-assets'); setup.mkdir(exist_ok=True)
from prepare_robot import prepare_robot
prepare_robot(setup)
subprocess.run(['ros2','run','clearpath_generator_common','generate_description','-s',str(setup)],check=True)
xml=subprocess.check_output(['ros2','run','xacro','xacro',str(setup/'robot.urdf.xacro')])
robot=ET.fromstring(xml)
parents={}

def transform(origin):
    if origin is None: return [0,0,0],[0,0,0,1]
    xyz=list(map(float,origin.get('xyz','0 0 0').split()))
    roll,pitch,yaw=map(float,origin.get('rpy','0 0 0').split())
    return xyz,quat_from_ypr([yaw,pitch,roll])

for joint in robot.findall('joint'):
    parents[joint.find('child').get('link')]=(joint.find('parent').get('link'),*transform(joint.find('origin')))

def link_transform(name):
    if name not in parents: return [0,0,0],[0,0,0,1]
    parent,local,q=parents[name]; p,Q=link_transform(parent)
    offset=rotate(Q,local)
    return [p[i]+offset[i] for i in range(3)],quat_multiply(Q,q)

items=[]; packages={}
for link in robot.findall('link'):
    p,q=link_transform(link.get('name'))
    for visual in link.findall('visual'):
        mesh=visual.find('geometry/mesh')
        if mesh is None: continue
        filename=mesh.get('filename')
        if filename.startswith('package://'):
            package,relative=filename.removeprefix('package://').split('/',1)
            share=Path(get_package_share_directory(package)); path=share/relative
            packages[package]=ET.parse(share/'package.xml').getroot()
        else: path=Path(filename.removeprefix('file://'))
        if path.suffix=='.dae' and path.with_suffix('.stl').exists(): path=path.with_suffix('.stl')
        if path.suffix not in ('.stl','.dae'): raise ValueError(f'Unsupported visual: {path}')
        identity=hashlib.sha256(str(path).encode()).hexdigest()[:12]+path.suffix
        shutil.copyfile(path,output/identity)
        local,Q=transform(visual.find('origin')); offset=rotate(q,local)
        rgba=visual.find('material/color')
        if rgba is None:
            material=visual.find('material')
            if material is not None:
                definition=next((m for m in robot.findall('material') if m.get('name')==material.get('name')),None)
                if definition is not None:rgba=definition.find('color')
        joint=next((j for j in robot.findall('joint') if j.find('child').get('link')==link.get('name')),None)
        axis=joint.find('axis') if joint is not None else None
        items.append({'file':identity,'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'link':link.get('name'),'joint_name':joint.get('name') if joint is not None else None,
                      'joint_axis':list(map(float,axis.get('xyz','0 0 1').split())) if axis is not None else [0,0,1],
                      'position':[p[i]+offset[i] for i in range(3)],'quaternion_xyzw':quat_multiply(q,Q),
                      'scale':list(map(float,mesh.get('scale','1 1 1').split())),
                      'color':list(map(float,rgba.get('rgba').split()))[:3] if rgba is not None else [.7,.55,.12]})
licenses=[]
for name,xml in packages.items():
    licenses.append({'package':name,'version':xml.findtext('version'),
                     'licenses':[e.text for e in xml.findall('license')],
                     'source':'https://github.com/clearpathrobotics/clearpath_common',
                     'copyright':'Clearpath Robotics; see upstream source and installed package license'})
(output/'model.json').write_text(json.dumps({'model':'Husky A200','origin':'Official Clearpath URDF visual assets',
                                            'packages':licenses,'meshes':items},indent=2))
(output/'NOTICE.json').write_text(json.dumps(licenses,indent=2))
(output/'robot.urdf').write_bytes(subprocess.check_output(['ros2','run','xacro','xacro',str(setup/'robot.urdf.xacro')]))
print('Official Husky visual assets:',len(items),'meshes ->',output)
