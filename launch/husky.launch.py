"""Launch upstream Gazebo and Clearpath robot on the exported shared scene."""
import os
import json
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    root=Path(__file__).resolve().parents[1]
    runtime=Path(os.environ.get('RADIO_LAB_RUNTIME',root/'.runtime'))
    scene=json.loads((runtime/'active_scene.json').read_text())['scenario']
    robot=scene['robot']
    clearpath=get_package_share_directory('clearpath_gz')
    gz=get_package_share_directory('ros_gz_sim')
    resources=':'.join([os.path.join(p,'share') for p in os.environ['AMENT_PREFIX_PATH'].split(':')])
    return LaunchDescription([
        DeclareLaunchArgument('world_file',default_value=str(runtime/'world.sdf')),
        DeclareLaunchArgument('setup_path',default_value=os.environ.get('CLEARPATH_SETUP_PATH','/tmp/clearpath')),
        DeclareLaunchArgument('gz_args',default_value='-r -s'),
        SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH',resources),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(gz,'launch','gz_sim.launch.py')),
            launch_arguments={'gz_args':[LaunchConfiguration('gz_args'),' ',LaunchConfiguration('world_file')]}.items()),
        Node(package='ros_gz_bridge',executable='parameter_bridge',
             arguments=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock']),
        Node(package='ros_gz_bridge',executable='parameter_bridge',
             arguments=['/husky/world_pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V'],
             remappings=[('/husky/world_pose','/simulation/poses')]),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(root/'launch/navigation.launch.py'))),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(clearpath,'launch','robot_spawn.launch.py')),
            launch_arguments={'world':'radio_world','setup_path':LaunchConfiguration('setup_path'),
                              'x':str(robot['position'][0]),'y':str(robot['position'][1]),'z':str(robot['position'][2]),'yaw':str(robot['yaw_rad']),'use_sim_time':'true','rviz':'false'}.items())
    ])
