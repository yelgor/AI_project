"""Run inside the sourced ROS container to exercise native command serialization."""
import threading
import time
import types
import unittest
try:
    from app.husky_runtime import Runtime
    from rclpy.clock import Clock
    from rclpy.serialization import serialize_message
    AVAILABLE=True
except ModuleNotFoundError:
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE,'ROS packages: run this test in the husky container')
class RosRuntimeTests(unittest.TestCase):
    def test_zero_command_after_stop_is_serializable(self):
        messages=[]
        node=types.SimpleNamespace(authority='teleop',lock=threading.RLock(),
            command=(0,0),command_time=time.monotonic(),get_clock=lambda:Clock(),
            publisher=types.SimpleNamespace(publish=messages.append))
        Runtime.publish_control(node)
        self.assertIsInstance(messages[0].twist.linear.x,float)
        self.assertIsInstance(messages[0].twist.angular.z,float)
        self.assertTrue(serialize_message(messages[0]))


if __name__=='__main__':unittest.main()
