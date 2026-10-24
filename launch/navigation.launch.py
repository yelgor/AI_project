"""Static-map Nav2 with upstream plugins and explicit Gazebo localization."""
from pathlib import Path
import copy
import yaml
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root/'config/nav2.yaml').read_text())
    namespace = 'a200_0000'
    remaps = [('/tf','tf'),('/tf_static','tf_static'),('cmd_vel','nav_cmd_vel')]
    nodes = []
    packages = {'map_server':'nav2_map_server','planner_server':'nav2_planner',
                'controller_server':'nav2_controller','behavior_server':'nav2_behaviors',
                'bt_navigator':'nav2_bt_navigator'}
    file = root/'.runtime/navigation/costmaps.yaml'
    file.write_text(yaml.safe_dump({f'/{namespace}/{key}/{key}': {'ros__parameters':
        dict(copy.deepcopy(config['costmap']), use_sim_time=True)} for key in ('global_costmap','local_costmap')}))
    for name, package in packages.items():
        params = dict(config.get(name, {}))
        if name == 'map_server': params['yaml_filename'] = str(root/'.runtime/navigation/map.yaml')
        parameters = [config['common'], params]
        if name in ('planner_server','controller_server'):
            parameters.append(str(file))
        nodes.append(Node(package=package, executable=name, name=name, namespace=namespace,
                          parameters=parameters, remappings=remaps, output='screen'))
    nodes.append(Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='navigation_lifecycle_manager', namespace=namespace,
        parameters=[{'use_sim_time':True,'autostart':True,'node_names':list(packages),
                     'bond_timeout':10.0}], output='screen'))
    return LaunchDescription(nodes)
