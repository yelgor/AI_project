"""Launch upstream Gazebo and Clearpath robot on the exported shared scene."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    clearpath=get_package_share_directory('clearpath_gz')
    gz=get_package_share_directory('ros_gz_sim')
    resources=':'.join([os.path.join(p,'share') for p in os.environ['AMENT_PREFIX_PATH'].split(':')])
    return LaunchDescription([
        DeclareLaunchArgument('world_file',default_value='/project/.runtime/world.sdf'),
        DeclareLaunchArgument('setup_path',default_value='/tmp/clearpath'),
        DeclareLaunchArgument('gz_args',default_value='-r -s'),
        SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH',resources),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(gz,'launch','gz_sim.launch.py')),
            launch_arguments={'gz_args':[LaunchConfiguration('gz_args'),' ',LaunchConfiguration('world_file')]}.items()),
        Node(package='ros_gz_bridge',executable='parameter_bridge',
             arguments=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock']),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(clearpath,'launch','robot_spawn.launch.py')),
            launch_arguments={'world':'radio_world','setup_path':LaunchConfiguration('setup_path'),
                              'x':'-10','y':'10','z':'0.3','use_sim_time':'true','rviz':'false'}.items())
    ])
