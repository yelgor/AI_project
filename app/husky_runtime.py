"""Owned Gazebo process supervisor, ROS world-pose telemetry and deadman control."""
import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from ament_index_python.packages import get_package_share_directory
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped, Twist, PoseStamped, TransformStamped
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from rclpy.action import ActionClient
from tf2_ros import TransformBroadcaster
from lifecycle_msgs.srv import GetState
try:
    from .scenario import quat_multiply, rotate
    from .navigation import free
    from .provenance import implementation_hash
except ImportError:
    from scenario import quat_multiply, rotate
    from navigation import free
    from provenance import implementation_hash
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from std_msgs.msg import String
from rclpy.qos import qos_profile_sensor_data

ROOT=Path(__file__).resolve().parents[1]


class Runtime(Node):
    def __init__(self):
        super().__init__('constructor_husky_runtime',cli_args=['--ros-args','-r','/tf:=/a200_0000/tf'])
        self.lock=threading.RLock(); self.operation=threading.Lock()
        self.process=None; self.log=None; self.revision=None; self.pose=None; self.velocity=None
        self.command=(0.,0.); self.command_time=0; self.closed=False; self.last_telemetry=0
        self.radio_url=os.environ.get('RADIO_URL','http://radio:8000')
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.publisher=self.create_publisher(TwistStamped,'/a200_0000/platform/cmd_vel',10)
        self.measurements=self.create_publisher(String,'/radio/measurement',10)
        self.last_measurement=None
        self.implementation_sha256=implementation_hash();self.navigation_config_sha256=None
        self.versions={name:ET.parse(Path(get_package_share_directory(name))/'package.xml').getroot().findtext('version')
                       for name in ('nav2_planner','nav2_controller','clearpath_gz')}
        self.last_radio_ack=time.monotonic()
        self.authority='teleop'; self.nav_velocity=(0.,0.); self.nav_time=0
        self.nav_handle=None; self.nav_status='idle'; self.nav_generation=0; self.odom=None
        self.lifecycle_states={}; self.lifecycle_clients={name:self.create_client(GetState,f'/a200_0000/{name}/get_state')
            for name in ('planner_server','controller_server','bt_navigator')}
        self.create_timer(1.,self.check_lifecycle)
        self.tf=TransformBroadcaster(self)
        self.planner=ActionClient(self,ComputePathToPose,'/a200_0000/compute_path_to_pose')
        self.navigator=ActionClient(self,NavigateToPose,'/a200_0000/navigate_to_pose')
        self.create_subscription(Twist,'/a200_0000/nav_cmd_vel',self.on_nav_velocity,10)
        self.create_subscription(TFMessage,'/simulation/poses',self.on_pose,qos_profile_sensor_data)
        self.create_subscription(Odometry,'/a200_0000/platform/odom/filtered',self.on_odom,qos_profile_sensor_data)
        self.create_timer(.05,self.publish_control)
        self.sender=threading.Thread(target=self.send_telemetry,daemon=True); self.sender.start()

    def on_pose(self,message):
        for item in message.transforms:
            if item.child_frame_id=='a200_0000/robot':
                t=item.transform.translation; q=item.transform.rotation
                with self.lock:
                    self.pose={'position':[t.x,t.y,t.z],'quaternion_xyzw':[q.x,q.y,q.z,q.w],
                               'sim_time_s':item.header.stamp.sec+item.header.stamp.nanosec*1e-9}
                self.publish_localization()
                break

    def on_odom(self,message):
        v=message.twist.twist
        with self.lock:
            self.velocity={'linear_velocity':[v.linear.x,v.linear.y,v.linear.z],
                           'angular_velocity':[v.angular.x,v.angular.y,v.angular.z]}
            self.odom=message

    def publish_localization(self):
        """Ground truth map->odom; upstream robot publishes odom->base_link."""
        with self.lock:
            if not self.pose or self.odom is None: return
            p=self.odom.pose.pose.position; q=self.odom.pose.pose.orientation
            rotation=quat_multiply(self.pose['quaternion_xyzw'],[-q.x,-q.y,-q.z,q.w])
            offset=rotate(rotation,[p.x,p.y,p.z])
            translation=[self.pose['position'][i]-offset[i] for i in range(3)]
            tf=TransformStamped(); tf.header.stamp=self.get_clock().now().to_msg()
            tf.header.frame_id='map'; tf.child_frame_id=self.odom.header.frame_id or 'odom'
            tf.transform.translation.x,tf.transform.translation.y,tf.transform.translation.z=translation
            tf.transform.rotation.x,tf.transform.rotation.y,tf.transform.rotation.z,tf.transform.rotation.w=rotation
        self.tf.sendTransform(tf)

    def on_nav_velocity(self,message):
        with self.lock:
            self.nav_velocity=(message.linear.x,message.angular.z); self.nav_time=time.monotonic()

    def check_lifecycle(self):
        revision=self.revision
        for name,client in self.lifecycle_clients.items():
            if not client.service_is_ready(): continue
            def done(future,key=name,rev=revision):
                try:
                    result=future.result()
                    with self.lock:
                        if rev==self.revision: self.lifecycle_states[key]=(result.current_state.id,time.monotonic())
                except Exception: pass
            client.call_async(GetState.Request()).add_done_callback(done)

    def publish_control(self):
        if self.authority=='nav' and time.monotonic()-self.last_radio_ack>4:
            self.get_logger().error('Radio backend unavailable: cancelling autonomous motion')
            self.hold()
        with self.lock:
            if self.authority=='nav':
                linear,angular=self.nav_velocity if time.monotonic()-self.nav_time<.5 else (0.,0.)
            else:
                linear,angular=self.command if self.authority=='teleop' and time.monotonic()-self.command_time<.5 else (0.,0.)
        msg=TwistStamped(); msg.header.stamp=self.get_clock().now().to_msg()
        msg.twist.linear.x=linear; msg.twist.angular.z=angular
        self.publisher.publish(msg)

    def send_telemetry(self):
        while not self.closed:
            with self.lock:
                pose=dict(self.pose,scene_revision=self.revision,navigation=self.navigation_state(),**(self.velocity or {})) if self.pose and self.process and self.process.poll() is None else None
            if pose:
                try:
                    request=urllib.request.Request(self.radio_url+'/api/robot/telemetry',json.dumps(pose).encode(),{'Content-Type':'application/json'})
                    response=json.load(self.http.open(request,timeout=3))
                    self.last_radio_ack=time.monotonic()
                    measurement=response.get('measurement')
                    signature=json.dumps(measurement,sort_keys=True) if measurement else None
                    if measurement and signature!=self.last_measurement:
                        self.measurements.publish(String(data=json.dumps(measurement)))
                        self.last_measurement=signature
                except Exception as error:
                    if time.monotonic()-self.last_telemetry>5:
                        self.get_logger().warning(f'Telemetry: {error}'); self.last_telemetry=time.monotonic()
            time.sleep(.1)

    def start(self,revision):
        with self.operation:
            self.stop_owned()
            active=json.loads((ROOT/'.runtime/active_scene.json').read_text())
            if active['revision']!=revision: raise ValueError('Scene revision does not match exported world')
            env=dict(os.environ); env['SCENE_REVISION']=revision
            self.navigation_config_sha256=hashlib.sha256((ROOT/'config/nav2.yaml').read_bytes()).hexdigest()
            self.log=open(ROOT/'.runtime/husky.log','a')
            self.process=subprocess.Popen(['ros2','launch',str(ROOT/'launch/husky.launch.py')],
                                          stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
            with self.lock:
                self.revision=revision; self.pose=None; self.command=(0,0); self.last_measurement=None; self.lifecycle_states={}
            return {'status':'starting','pid':self.process.pid}

    def stop_owned(self):
        self.cancel_navigation()
        with self.lock:
            self.command=(0,0); self.command_time=time.monotonic(); self.pose=None
            process=self.process; self.process=None; self.odom=None; self.authority='teleop'; self.lifecycle_states={}
        if process and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGINT)
            except ProcessLookupError:pass
            try: process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL); process.wait()
        if self.log: self.log.close(); self.log=None
        return {'status':'stopped'}

    def stop(self):
        with self.operation: return self.stop_owned()

    def control(self,data):
        linear,angular=float(data['linear']),float(data['angular'])
        if not (-1<=linear<=1 and -1.5<=angular<=1.5): raise ValueError('Control limits exceeded')
        with self.lock:
            if not self.process or self.process.poll() is not None: raise ValueError('Husky is stopped')
            if self.authority!='teleop':
                # Key release/blur sends a harmless zero; it must not cancel autonomy.
                if linear==0 and angular==0: return {'status':'ignored','authority':self.authority}
                raise ValueError('Autonomous control active; cancel navigation or stop the experiment first')
            self.command=(linear,angular); self.command_time=time.monotonic()
        return {'status':'ok'}

    def navigation_state(self):
        active=all(self.lifecycle_states.get(name,(0,0))[0]==3 and
                   time.monotonic()-self.lifecycle_states[name][1]<5 for name in self.lifecycle_clients)
        return {'ready':rclpy.ok() and active and self.planner.server_is_ready() and self.navigator.server_is_ready(),
                'status':self.nav_status,'authority':self.authority,
                'generation':self.nav_generation,
                'software':self.versions,
                'implementation_sha256':self.implementation_sha256,
                'navigation_config_sha256':self.navigation_config_sha256,
                'localization':'Gazebo ground truth','static_obstacles_only':True}

    def wait_future(self,future,timeout=25):
        event=threading.Event(); future.add_done_callback(lambda _:event.set())
        if not event.wait(timeout): raise TimeoutError('Nav2 response timeout')
        return future.result()

    def goal_pose(self,data):
        import math
        values=data['position']
        if len(values) not in (2,3) or not all(math.isfinite(float(v)) and abs(float(v))<10000 for v in values):
            raise ValueError('Navigation position must be finite [x,y] or [x,y,yaw]')
        pose=PoseStamped(); pose.header.frame_id='map'; pose.header.stamp=self.get_clock().now().to_msg()
        pose.pose.position.x=float(values[0]); pose.pose.position.y=float(values[1])
        yaw=float(values[2]) if len(values)==3 else 0.
        pose.pose.orientation.z=math.sin(yaw/2); pose.pose.orientation.w=math.cos(yaw/2)
        return pose

    def plan(self,data):
        import math
        if not self.planner.wait_for_server(timeout_sec=3): raise ValueError('Nav2 planner not ready')
        goal=ComputePathToPose.Goal(); goal.goal=self.goal_pose(data); goal.planner_id='GridBased'; goal.use_start='start' in data
        scene=json.loads((ROOT/'.runtime/active_scene.json').read_text())['scenario']
        if not free(scene,goal.goal.pose.position.x,goal.goal.pose.position.y,.55):
            raise ValueError('Nav2 goal lacks footprint clearance')
        if goal.use_start:goal.start=self.goal_pose({'position':data['start']})
        with self.lock:
            origin=data['start'][:2] if goal.use_start else (self.pose['position'][:2] if self.pose else None)
        handle=self.wait_future(self.planner.send_goal_async(goal))
        if not handle.accepted: raise ValueError('Nav2 rejected plan')
        result=self.wait_future(handle.get_result_async())
        points=[[p.pose.position.x,p.pose.position.y] for p in result.result.path.poses]
        if result.status!=4 or len(points)<1: raise ValueError('Nav2: no reachable path')
        length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
        if origin:length+=math.dist(origin,points[0])
        length+=math.dist(points[-1],data['position'][:2])
        return {'path':points,'length_m':length}

    def navigate(self,data):
        if not self.navigator.wait_for_server(timeout_sec=3): raise ValueError('Nav2 navigator not ready')
        self.cancel_navigation()
        generation=self.nav_generation
        goal=NavigateToPose.Goal(); goal.pose=self.goal_pose(data)
        handle=self.wait_future(self.navigator.send_goal_async(goal))
        if not handle.accepted: raise ValueError('Nav2 rejected goal')
        with self.lock:
            if generation!=self.nav_generation or not self.process or self.process.poll() is not None:
                if rclpy.ok():handle.cancel_goal_async()
                raise ValueError('Navigation cancelled while accepting the goal')
            self.nav_handle=handle; self.nav_status='running'; self.authority='nav'
            self.nav_time=0
        def done(future):
            try:result=future.result()
            except Exception:return
            with self.lock:
                if generation!=self.nav_generation: return
                self.nav_status={4:'succeeded',5:'cancelled',6:'failed'}.get(result.status,'failed')
                self.nav_handle=None; self.authority='hold'; self.nav_velocity=(0.,0.)
        handle.get_result_async().add_done_callback(done)
        return self.navigation_state()

    def cancel_navigation(self):
        with self.lock:
            handle=self.nav_handle; self.nav_handle=None; self.nav_generation+=1
            self.nav_status='idle'; self.authority='teleop'; self.command=(0.,0.); self.nav_velocity=(0.,0.); self.nav_time=0
        if handle and rclpy.ok(): handle.cancel_goal_async()
        return self.navigation_state()

    def hold(self):
        self.cancel_navigation()
        with self.lock: self.authority='hold'
        return self.navigation_state()


def main():
    rclpy.init(); node=Runtime(); node.set_parameters([rclpy.parameter.Parameter('use_sim_time',value=True)])
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,data):
            body=json.dumps(data).encode(); self.send_response(status)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self): self.respond(200,{'status':'ok','navigation':node.navigation_state()})
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=4096: raise ValueError('Invalid body length')
                data=json.loads(self.rfile.read(length))
                if self.path=='/start': result=node.start(data['revision'])
                elif self.path=='/stop': result=node.stop()
                elif self.path=='/control': result=node.control(data)
                elif self.path=='/nav/plan': result=node.plan(data)
                elif self.path=='/nav/goal': result=node.navigate(data)
                elif self.path=='/nav/cancel': result=node.cancel_navigation()
                elif self.path=='/nav/hold': result=node.hold()
                else: raise ValueError('Unknown route')
                self.respond(200,result)
            except Exception as error: self.respond(400,{'error':str(error)})
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('0.0.0.0',8766),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try: rclpy.spin(node)
    except (KeyboardInterrupt,rclpy.executors.ExternalShutdownException): pass
    finally:
        node.closed=True; node.stop(); server.shutdown(); server.server_close()
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__=='__main__': main()
