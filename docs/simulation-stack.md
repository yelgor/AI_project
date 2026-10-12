# Перевірений стан середовища

## Реалізований стек

- Sionna RT 2.2.0 / Mitsuba / Dr.Jit, CPU LLVM backend.
- Browser 3D-конструктор Three.js: приміщення, Tx/Rx, official Husky visual assets.
- Ubuntu 24.04 / ROS 2 Jazzy / Gazebo Harmonic / Clearpath Simulator 2.9.4.
- Shared scene v2, SDF/mesh export, world pose PosePublisher, 3D antenna mount.
- Ручне керування, recording/grid, metadata/CSV/JSONL/events/ZIP.

## Перевірено в поточній хмарній машині

- 9 Python tests: Friis/absolute delay, multipath, hollow room/door,
  rotated geometry, full rigid antenna transform, validation/migration,
  dataset snapshot/CSV/CIR/ZIP та grid на двох висотах.
- Browser end-to-end: viewport WebGL, 6 офіційних visual meshes, редагування Rx.Z,
  Apply/measure, multi-height grid, завантаження ZIP саме цього job,
  без JavaScript page errors. Chromium із software WebGL.
- Radio API і constructor frontend працюють у radio Docker-container.
- Full integration: Room → official Husky → named Gazebo world pose → antenna
  зі зміщенням і yaw → запис. Рух 0.649 м, 6 dataset rows; перевірені
  фактичні координати, sim time, velocity, CIR, CSV/JSONL/ZIP.
  Повторно після переходу контейнерів на UID/GID checkout: рух 0.725 м,
  5 rows, той самий full check пройшов; world export більше не потребує root.
- Radio Dockerfile зібраний/перевірений з libLLVM19 і libatomic1 та trusted CA.
- Clearpath/Gazebo установлені з офіційних signed apt packages у ROS-контейнері.

Приклади перевірених результатів — examples/datasets/demo-grid.zip та
examples/datasets/demo-husky.zip. Screenshot конструктора — docs/constructor.png.
Старий CLI/smoke збережені для сумісності, але новий робочий інтерфейс — app/builder.py.

## Межі перевірки

Husky image поточної машини створений зі встановленого ROS-контейнера,
після виконання тих самих apt-команд, що у Dockerfile.husky (також був
python3-numpy). Окрема свіжа збірка Husky Dockerfile на іншій машині ще
не виконана. Підготовка Python/frontend та startup складових перевірені;
повний fresh-machine run_demo і cloud publication/restore не доведені.
Docker tags локальні, не опубліковані у registry.

Хост — Debian 13, ROS працює в Ubuntu-контейнері. Docker storage driver vfs
дублює файлові системи контейнерів, що призвело до повного диска під час
попередньої підготовки. Зайві власні артефакти прибрані; Husky і supervisor
ділять один контейнер. Scripts не виконують автоматичний prune чужих ресурсів.

Попереднє обмеження packages.ros.org (403) усунуто доступом у середовищі.
TLS-проксі потребував trusted CA для pip у Docker; verification не вимикалася.
На машині є /usr/bin/chromium; окремий Playwright browser download не потрібен.

Повнохвильова/емпірична точність всіх ефектів не гарантована. Не реалізовані
modem PHY, RF-корпус робота, GPR/Nav2, multiuser/auth або streamed Gazebo desktop.
Browser constructor реалізований і підтримує local access; cloud preview автоматично
не надається. User guide пояснює доступ і формат збереження даних.

Ресурси та процеси після публікації треба повторно перевіряти. Checkout уже
ізольований; додатковий worktree без запиту не потрібний.
