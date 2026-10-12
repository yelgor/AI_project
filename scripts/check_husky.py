"""Drive the simulated Husky briefly and verify odometry plus radio output."""
import json
import math
import time
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import String

rclpy.init()
node=Node('check_husky',parameter_overrides=[Parameter('use_sim_time',value=True)])
positions=[]
measurements=[]
def on_odom(message):
    p=message.pose.pose.position
    positions.append((p.x,p.y))
def on_radio(message):
    measurements.append(json.loads(message.data))
node.create_subscription(Odometry,'/a200_0000/platform/odom/filtered',on_odom,qos_profile_sensor_data)
node.create_subscription(String,'/radio/measurement',on_radio,10)
publisher=node.create_publisher(TwistStamped,'/a200_0000/platform/cmd_vel',10)
try:
    deadline=time.monotonic()+60
    while not positions and time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.2)
    if not positions: raise RuntimeError('No Husky odometry within 60 seconds')
    start=positions[-1]
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        cmd=TwistStamped(); cmd.header.stamp=node.get_clock().now().to_msg(); cmd.twist.linear.x=.3
        publisher.publish(cmd)
        rclpy.spin_once(node,timeout_sec=.1)
    moved=math.dist(start,positions[-1])
    if moved<.1: raise RuntimeError(f'Husky did not move: {moved:.3f}m')
    deadline=time.monotonic()+30
    while not measurements and time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.2)
    if not measurements or not any(m.get('path_count',0)>0 for m in measurements):
        raise RuntimeError('No nonzero ROS radio measurement')
    print(f'Husky integration OK: moved {moved:.3f}m; radio measurements {len(measurements)}')
finally:
    publisher.publish(TwistStamped())
    node.destroy_node()
    rclpy.shutdown()
