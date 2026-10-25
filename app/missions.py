"""Physical shadowing missions built from shared Gazebo/Sionna geometry."""
import copy
import math
try:
    from .scenario import preset,normalize
except ImportError:
    from scenario import preset,normalize


def line_of_sight(scene, receiver):
    """Diagnostic geometric visibility; never substitutes for measured RSSI."""
    start=scene['tx']['position']; delta=[receiver[i]-start[i] for i in range(3)]
    for obj in scene['objects']:
        if obj['center'][2]+obj['size'][2]/2<=.01:continue
        c,s=math.cos(obj['yaw_rad']),math.sin(obj['yaw_rad'])
        d=[start[i]-obj['center'][i] for i in range(3)]
        origin=[c*d[0]+s*d[1],-s*d[0]+c*d[1],d[2]]
        direction=[c*delta[0]+s*delta[1],-s*delta[0]+c*delta[1],delta[2]]
        lower,upper=0.,1.
        for i in range(3):
            half=obj['size'][i]/2
            if abs(direction[i])<1e-10:
                if abs(origin[i])>=half:lower,upper=1.,0.;break
            else:
                a=(-half-origin[i])/direction[i];b=(half-origin[i])/direction[i]
                lower=max(lower,min(a,b));upper=min(upper,max(a,b))
        if upper>max(lower,1e-6) and lower<1-1e-6:return False
    return True


def mission(name='shadow',layout=0):
    if name not in ('shadow','office','warehouse','district','courtyard'):raise ValueError('Unknown mission')
    scene=preset('empty');floor=scene['objects'][0]
    scene['name']=name+('-b' if layout else '-a')
    # Anchors screened with upstream Sionna at the centre and four ±0.15m
    # neighbours; runtime validates them again before any experimental motion.
    anchors={'shadow':[[4,2],[4,3]],'office':[[4,3],[5,4]],
             'warehouse':[[5,1],[5,2]],'district':[[4,3],[5,4.5]],
             'courtyard':[[4,3],[5.5,4]]}
    anchor=anchors[name][bool(layout)]
    route=[[-4,3.5,math.pi/2],[anchor[0],3.5,0],
           [*anchor,math.pi/2 if anchor[1]>3.5 else -math.pi/2]]
    spawn=[-4,-3.5,.3];tx=[-4,-3.5,1.5];bounds=[-7,-6,7,6]
    def box(identity,center,size,material='concrete',yaw=0):
        scene['objects'].append(dict(floor,id=identity,label=identity,center=center,size=size,material=material,yaw_rad=yaw))
    box('shadow-building',[0,0,2],[4,4,4])
    if name=='office':
        # Multiple enclosed rooms and wide door gaps around the main radio obstacle.
        for i,(x,y,w,h) in enumerate([(-7,0,.2,12),(7,0,.2,12),(0,6,14,.2),
            (-6,1.5,2,.2),(6,1.5,2,.2),(-6,-3,2,.2),(6,-3,2,.2),
            (0,-6,14,.2)]):box(f'office-wall-{i}',[x,y,1.5],[w,h,3])
    if name=='warehouse':
        for i,(x,y) in enumerate([(-7,-3),(-7,3),(7,-3),(7,3),(-.8,6),(.8,-6)]):
            box(f'shelf-{i}',[x,y,1.4],[1.3,3.2,2.8],'metal')
        bounds=[-9,-9,9,9]
    if name in ('district','courtyard'):
        for i,(x,y,w,h) in enumerate([(-8,1,3,5),(8,-1,3,5),(0,8,5,3),(0,-8,5,3)]):
            box(f'building-{i}',[x,y,2.5],[w,h,5],'brick' if i%2 else 'concrete')
        bounds=[-11,-11,11,11]
    if name=='courtyard':
        for i,(x,y) in enumerate([(-6,-7),(6,7),(-7,7),(7,-7)]):
            box(f'courtyard-block-{i}',[x,y,.7],[1.3,1.3,1.4],'wood',.3*i)
    if layout:
        tx=[-5,-2.8,1.8]
    scene.update(tx={'position':tx,'orientation_rad':[0,0,0]},
        rx={'mode':'husky','position':[0,0,1],'orientation_rad':[0,0,0],
            'mount_position':[0,0,.7],'mount_orientation_rad':[0,0,0]},
        robot={'position':spawn,'yaw_rad':math.pi/2})
    scene=normalize(scene)
    scene['radio']['period_s']=.5
    config={'method':'B1','beta':0,'q_safe_dbm':-47,'hysteresis_db':1,
        'degraded_s':1,'stable_s':1,'timeout_s':150,'bounds':bounds,
        'grid_step_m':1.5,'route':route,'label':scene['name'],'monitor_window_s':2,
        'save_cir':False,'require_shadow_loss':True,'shadow_goal':anchor,'shadow_radius_m':.15}
    return {'id':name,'title':{'shadow':'Заїзд за будівлю','office':'Офіс і суміжні кімнати',
        'warehouse':'Склад зі стелажами','district':'Квартал і проїзди','courtyard':'Двір з перешкодами'}[name],
        'description':'Husky з Rx → рух до радіотіні → втрата RSSI → автономне повернення',
        'scene':scene,'config':config}


def catalog():
    return [{k:v for k,v in mission(name).items() if k not in ('scene','config')}
            for name in ('shadow','office','warehouse','district','courtyard')]


def response_defaults(profile='responsive'):
    if profile=='benchmark':return {'loss_policy':'anchor','monitor_window_s':2,'degraded_s':1,'stable_s':1,'stale_s':8}
    if profile!='responsive':raise ValueError('Unknown response profile')
    return {'loss_policy':'responsive','monitor_window_s':.5,'degraded_s':.5,'stable_s':1,
            'hysteresis_db':1,'stale_s':1.5,'require_shadow_loss':False,'max_sample_travel_m':.5}
