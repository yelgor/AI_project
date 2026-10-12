"""Owned Gazebo process supervisor, ROS world-pose telemetry and deadman control."""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from std_msgs.msg import String
from rclpy.qos import qos_profile_sensor_data

ROOT=Path(__file__).resolve().parents[1]


class Runtime(Node):
    def __init__(self):
        super().__init__('constructor_husky_runtime')
        self.lock=threading.RLock(); self.operation=threading.Lock()
        self.process=None; self.log=None; self.revision=None; self.pose=None; self.velocity=None
        self.command=(0.,0.); self.command_time=0; self.closed=False; self.last_telemetry=0
        self.radio_url=os.environ.get('RADIO_URL','http://radio:8000')
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.publisher=self.create_publisher(TwistStamped,'/a200_0000/platform/cmd_vel',10)
        self.measurements=self.create_publisher(String,'/radio/measurement',10)
        self.last_measurement=None
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
                break

    def on_odom(self,message):
        v=message.twist.twist
        with self.lock: self.velocity={'linear_velocity':[v.linear.x,v.linear.y,v.linear.z],
                                       'angular_velocity':[v.angular.x,v.angular.y,v.angular.z]}

    def publish_control(self):
        with self.lock:
            linear,angular=self.command if time.monotonic()-self.command_time<.5 else (0.,0.)
        msg=TwistStamped(); msg.header.stamp=self.get_clock().now().to_msg()
        msg.twist.linear.x=linear; msg.twist.angular.z=angular
        self.publisher.publish(msg)

    def send_telemetry(self):
        while not self.closed:
            with self.lock:
                pose=dict(self.pose,scene_revision=self.revision,**(self.velocity or {})) if self.pose and self.process and self.process.poll() is None else None
            if pose:
                try:
                    request=urllib.request.Request(self.radio_url+'/api/robot/telemetry',json.dumps(pose).encode(),{'Content-Type':'application/json'})
                    response=json.load(self.http.open(request,timeout=3))
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
            self.log=open(ROOT/'.runtime/husky.log','a')
            self.process=subprocess.Popen(['ros2','launch',str(ROOT/'launch/husky.launch.py')],
                                          stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
            with self.lock: self.revision=revision; self.pose=None; self.command=(0,0); self.last_measurement=None
            return {'status':'starting','pid':self.process.pid}

    def stop_owned(self):
        with self.lock:
            self.command=(0,0); self.command_time=time.monotonic(); self.pose=None
            process=self.process; self.process=None
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGINT)
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
            self.command=(linear,angular); self.command_time=time.monotonic()
        return {'status':'ok'}


def main():
    rclpy.init(); node=Runtime(); node.set_parameters([rclpy.parameter.Parameter('use_sim_time',value=True)])
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,data):
            body=json.dumps(data).encode(); self.send_response(status)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self): self.respond(200,{'status':'ok'})
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=4096: raise ValueError('Invalid body length')
                data=json.loads(self.rfile.read(length))
                if self.path=='/start': result=node.start(data['revision'])
                elif self.path=='/stop': result=node.stop()
                elif self.path=='/control': result=node.control(data)
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
