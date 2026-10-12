"""ROS 2 odometry -> Sionna HTTP -> radio measurement JSON topic."""
import json
import urllib.request
import urllib.error
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from std_msgs.msg import String


class RadioBridge(Node):
    def __init__(self):
        super().__init__('radio_bridge')
        self.declare_parameter('radio_url','http://radio:8000')
        self.declare_parameter('odom_topic','/a200_0000/platform/odom/filtered')
        self.declare_parameter('antenna_height_m',1.0)
        self.declare_parameter('period_s',1.0)
        self.declare_parameter('spawn_x',-10.0)
        self.declare_parameter('spawn_y',10.0)
        self.publisher=self.create_publisher(String,'/radio/measurement',10)
        # Docker-internal HTTP must not be sent to the external egress proxy.
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.pose=None
        self.create_subscription(Odometry,self.get_parameter('odom_topic').value,self.on_pose,qos_profile_sensor_data)
        self.create_timer(self.get_parameter('period_s').value,self.measure)

    def on_pose(self,message):
        self.pose=message

    def measure(self):
        if self.pose is None: return
        # In this demo spawn offset maps local odom origin to scene coordinates.
        p=self.pose.pose.pose.position
        payload={'position_m':[p.x+self.get_parameter('spawn_x').value,p.y+self.get_parameter('spawn_y').value,self.get_parameter('antenna_height_m').value]}
        request=urllib.request.Request(self.get_parameter('radio_url').value+'/sample',
                                     json.dumps(payload).encode(),{'Content-Type':'application/json'})
        try:
            result=json.load(self.http.open(request,timeout=30))
            result['odom_stamp']={'sec':self.pose.header.stamp.sec,'nanosec':self.pose.header.stamp.nanosec}
            result['source_frame']=self.pose.header.frame_id
            self.publisher.publish(String(data=json.dumps(result,allow_nan=False)))
        except (urllib.error.URLError,ValueError) as error:
            self.get_logger().error(f'Radio request failed: {error}')


def main():
    rclpy.init()
    node=RadioBridge()
    try: rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__=='__main__': main()
