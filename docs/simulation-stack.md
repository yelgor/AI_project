# Готовий стек симуляції

## Компоненти

| Компонент | Призначення | Перевірений стан хмарної машини |
| --- | --- | --- |
| Sionna RT 2.2.0 / Mitsuba / Dr.Jit | 3D радіопоширення, комплексні коефіцієнти й затримки шляхів | CPU-перевірка дала 4 ненульові шляхи |
| Ubuntu 24.04 / ROS 2 Jazzy | Середовище робототехніки | Docker-образ завантажений, ROS CLI запускається |
| Gazebo Harmonic / Clearpath Simulator | Фізика, будівлі, Husky A200 | Встановлення заблоковане доступом до ROS-репозиторію |

Sionna обчислює радіоканал, Gazebo — рух і фізику робота. Вони не обмінюються
геометрією, матеріалами чи позою автоматично. Потрібні узгоджені системи
координат, експорт сцени та ROS-адаптер. Це наступний етап реалізації.
Повнохвильова точність усіх електромагнітних ефектів не гарантується.

## Встановлення робототехнічного стеку

Хмарний хост — Debian 13, тому для офіційних Ubuntu-пакетів обрано Docker.
Перевірена команда базового ROS-контейнера:

```bash
docker pull ros:jazzy-ros-base
docker run --rm ros:jazzy-ros-base bash -lc \
  'source /opt/ros/jazzy/setup.bash; ros2 --help'
```

Далі слід виконати офіційну [інструкцію Clearpath](https://docs.clearpathrobotics.com/docs/ros/tutorials/simulator/install)
в Ubuntu 24.04 із ROS Jazzy. Потрібні пакети
`ros-jazzy-clearpath-simulator` і `ros-jazzy-ros-gz`.
У поточній спробі `apt-get update` отримав `403 Forbidden` від
`packages.ros.org`, тому встановлення цих пакетів не виконувалося.
Перевірки підписів пакетів і TLS не вимикалися.

У чернетці налаштувань хмарної мережі додані домени:
`packages.ros.org`, `packages.osrfoundation.org`, `docs.clearpathrobotics.com`,
`docs.ros.org`, `gazebosim.org`, `nvlabs.github.io`.
Їх збереження в чернетці не означає застосування до поточної машини.

## Доступ, редагування та дебаг

- Радіодвижок доступний з Python; код smoke-перевірки можна запускати під pdb
  або debugger IDE. Джерела встановлених пакетів доступні у virtualenv.
- Офіційний Clearpath підтримує Husky, конфігурацію `robot.yaml` і різні світи.
  Після встановлення виберіть конфігурацію Husky A200 за документацією й
  запускайте `ros2 launch clearpath_gz simulation.launch.py`.
- Середовища Gazebo можна редагувати у SDF та імпортувати 3D-моделі;
  Sionna використовує сцени Mitsuba й радіоматеріали. Конвертація між ними
  та перевірка збігу геометрії залишаються окремою задачею.
- GUI Gazebo/Blender потребує локального робочого місця або окремо
  налаштованого віддаленого робочого столу. Хмарна сесія його не надає.
- Перед оголошенням інтеграції готовою перевірте появу Husky, `/clock`,
  odometry, рух від cmd_vel та радіовимірювання при переміщенні.

Живі процеси та Docker-стан треба повторно перевіряти після публікації
хмарного середовища. Ізольована хмарна задача вже має checkout;
додатковий Git worktree без потреби створювати не слід.

## Офіційні джерела

- [Sionna RT](https://github.com/NVlabs/sionna-rt)
- [Документація Sionna](https://nvlabs.github.io/sionna/)
- [Gazebo з ROS](https://gazebosim.org/docs/latest/ros_installation/)
- [Clearpath Simulator](https://github.com/clearpathrobotics/clearpath_simulator/tree/jazzy)
