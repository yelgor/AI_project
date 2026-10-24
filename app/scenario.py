"""Shared versioned scene and rigid transforms, independent of simulation engines."""
import copy
import math
import re

MATERIALS = ['concrete', 'brick', 'plasterboard', 'wood', 'glass', 'metal']


def finite(value, name, low=None, high=None):
    if isinstance(value, bool): raise ValueError(f'{name}: expected number')
    number = float(value)
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        raise ValueError(f'{name}: invalid value')
    return number


def vector(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f'{name}: expected [x,y,z]')
    return [finite(v, name, -10000, 10000) for v in value]


def normalize(data):
    if not isinstance(data, dict): raise ValueError('Scenario must be a JSON object')
    if 'version' not in data:
        # Migration from the original box scene, preserving baseline radio settings.
        data = {'version': 2, 'name': 'Imported box scene',
                'objects': [dict(b, id=f'box-{i}', label=b.get('name', f'Box {i}'), yaw_rad=0)
                            for i,b in enumerate(data.get('buildings', []))],
                'tx': {'position': data['transmitter'], 'orientation_rad': [0,0,0]},
                'rx': {'mode':'static','position':[-10,10,1],'orientation_rad':[0,0,0],
                       'mount_position':[0,0,1],'mount_orientation_rad':[0,0,0]},
                'robot': {'position':[-10,10,.3], 'yaw_rad':0},
                'radio': {k:v for k,v in data.items() if k not in ('buildings','transmitter')}}
    if data.get('version') != 2: raise ValueError('Unsupported scenario version')
    result = copy.deepcopy(data)
    result['name'] = str(result.get('name','Untitled'))[:120]
    objects = result.get('objects',[])
    if not isinstance(objects,list) or len(objects)>100: raise ValueError('Maximum 100 objects')
    seen=set()
    for obj in objects:
        identity=obj.get('id','')
        if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identity) or identity in seen or identity in ('tx','rx','robot'):
            raise ValueError('Object ids must be unique, 1..80 letters/digits/_/-')
        seen.add(identity)
        obj['label']=str(obj.get('label',identity))[:100]
        obj['center']=vector(obj['center'],'object.center')
        obj['size']=vector(obj['size'],'object.size')
        if not all(.01<=v<=1000 for v in obj['size']): raise ValueError('Object sizes must be 0.01..1000m')
        obj['yaw_rad']=finite(obj.get('yaw_rad',0),'object.yaw_rad',-100,100)
        obj['material']=obj.get('material','concrete')
        if obj['material'] not in MATERIALS: raise ValueError('Unsupported ITU material')
        obj['thickness_m']=finite(obj.get('thickness_m',.2),'material.thickness_m',.001,10)
    tx=result['tx']; tx['position']=vector(tx['position'],'tx.position')
    tx['orientation_rad']=vector(tx.get('orientation_rad',[0,0,0]),'tx.orientation_rad')
    rx=result['rx']; rx['mode']=rx.get('mode','static')
    if rx['mode'] not in ('static','husky'): raise ValueError('Rx mode must be static or husky')
    for key,default in [('position',[-3,0,1]),('orientation_rad',[0,0,0]),('mount_position',[0,0,1]),('mount_orientation_rad',[0,0,0])]:
        rx[key]=vector(rx.get(key,default),'rx.'+key)
    robot=result['robot']; robot['position']=vector(robot['position'],'robot.position')
    robot['yaw_rad']=finite(robot.get('yaw_rad',0),'robot.yaw_rad',-100,100)
    if robot['position'][2]<0: raise ValueError('Robot spawn z must not be below ground')
    radio=result.setdefault('radio',{})
    for key,default,low,high in [('frequency_hz',2.4e9,1e8,1e11),('tx_power_dbm',20,-100,100),
                                ('bandwidth_hz',20e6,1,1e10),('noise_figure_db',5,0,100),('period_s',1,.2,60)]:
        radio[key]=finite(radio.get(key,default),key,low,high)
    solver=radio.setdefault('solver',{})
    for key,default,low,high in [('max_depth',3,0,8),('samples_per_src',10000,100,1000000),
                                ('max_num_paths_per_src',10000,100,1000000),('seed',42,0,2147483647)]:
        number=finite(solver.get(key,default),key,low,high)
        if not number.is_integer(): raise ValueError(f'{key}: expected integer')
        solver[key]=int(number)
    validate_position(result,tx['position'])
    validate_position(result,robot['position'])
    if rx['mode']=='static':
        validate_position(result,rx['position'])
        if math.dist(tx['position'],rx['position'])<.1: raise ValueError('Tx and Rx must be at least 0.1m apart')
    return result


def inside(obj, position, margin=0):
    dx,dy=position[0]-obj['center'][0],position[1]-obj['center'][1]
    yaw=obj.get('yaw_rad',0); c,s=math.cos(yaw),math.sin(yaw)
    local=[c*dx+s*dy,-s*dx+c*dy,position[2]-obj['center'][2]]
    return all(abs(local[i]) < obj['size'][i]/2+margin-1e-8 for i in range(3))


def validate_position(scene, position):
    for obj in scene['objects']:
        if inside(obj,position): raise ValueError(f'Position inside solid object: {obj["label"]}')


def quat_from_ypr(angles):
    yaw,pitch,roll=angles
    cy,sy=math.cos(yaw/2),math.sin(yaw/2)
    cp,sp=math.cos(pitch/2),math.sin(pitch/2)
    cr,sr=math.cos(roll/2),math.sin(roll/2)
    return [sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,cr*cp*sy-sr*sp*cy,cr*cp*cy+sr*sp*sy]


def quat_multiply(a,b):
    x,y,z,w=a; X,Y,Z,W=b
    return [w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z]


def rotate(q, v):
    length=math.sqrt(sum(x*x for x in q))
    if length<1e-8: raise ValueError('Invalid zero quaternion')
    q=[x/length for x in q]
    result=quat_multiply(quat_multiply(q,[*v,0]),[-q[0],-q[1],-q[2],q[3]])
    return result[:3]


def ypr_from_quat(q):
    length=math.sqrt(sum(x*x for x in q)); x,y,z,w=[v/length for v in q]
    return [math.atan2(2*(w*z+x*y),1-2*(y*y+z*z)),
            math.asin(max(-1,min(1,2*(w*y-z*x)))),
            math.atan2(2*(w*x+y*z),1-2*(x*x+y*y))]


def antenna_pose(scene, pose):
    offset=rotate(pose['quaternion_xyzw'],scene['rx']['mount_position'])
    q=quat_multiply(pose['quaternion_xyzw'],quat_from_ypr(scene['rx']['mount_orientation_rad']))
    return [pose['position'][i]+offset[i] for i in range(3)], ypr_from_quat(q)


def preset(name='room'):
    if name not in ('empty','room','corridor','warehouse','courtyard'): raise ValueError('Unknown preset')
    floor={'id':'floor','label':'Floor','center':[0,0,-.1],'size':[30,30,.2], 'material':'concrete','thickness_m':.2,'yaw_rad':0}
    objects=[floor]
    if name in ('room','corridor'):
        # 8x8 room, door in the south wall: width 1.6m, height 2.2m.
        for identity,center,size in [
            ('north',[0,4,1.5],[8,.2,3]),('west',[-4,0,1.5],[.2,8,3]),
            ('east',[4,0,1.5],[.2,8,3]),('door-left',[-2.4,-4,1.5],[3.2,.2,3]),
            ('door-right',[2.4,-4,1.5],[3.2,.2,3]),('lintel',[0,-4,2.6],[1.6,.2,.8])]:
            objects.append(dict(floor,id=identity,label=identity,center=center,size=size))
    if name=='corridor':
        objects += [dict(floor,id='partition-a',label='Partition',center=[0,1.9,1.5],size=[.2,4.2,3]),
                    dict(floor,id='partition-b',label='Partition lower',center=[0,-3,1.5],size=[.2,2,3])]
    if name=='warehouse':
        for i,x in enumerate((-3,0,3)):
            objects.append(dict(floor,id=f'shelf-{i}',label=f'Shelf {i+1}',center=[x,1,1.25],
                                size=[1.2,5,2.5],material='metal'))
    if name=='courtyard':
        for i,(x,y,w,h) in enumerate(((-3,2,3,4),(3,1,3,6),(0,7,8,2))):
            objects.append(dict(floor,id=f'building-{i}',label=f'Building {i+1}',
                                center=[x,y,2],size=[w,h,4]))
    robot_position=[-2,-2,.3] if name=='corridor' else [-1.5,-3,.3] if name=='warehouse' else [0,-2,.3]
    transmitter=[0,-4,1.5] if name=='courtyard' else [-1.5,4.5,1.5] if name=='warehouse' else [-2,2,1.5]
    return normalize({'version':2,'name':name,'objects':objects,
                      'tx':{'position':transmitter},'rx':{'mode':'static','position':[0,0,1.2] if name=='courtyard' else [2,2,1.2]},
                      'robot':{'position':robot_position,'yaw_rad':math.pi/2},'radio':{}})
