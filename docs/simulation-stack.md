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
modem PHY, RF-корпус робота, multiuser/auth або streamed Gazebo desktop.
Browser constructor реалізований і підтримує local access; cloud preview автоматично
не надається. User guide пояснює доступ і формат збереження даних.

Ресурси та процеси після публікації треба повторно перевіряти. Checkout уже
ізольований; додатковий worktree без запиту не потрібний.


## Автономні експерименти, 24 жовтня 2026

Додані Nav2 1.3.13 (NavFn/A*, Regulated Pure Pursuit), occupancy зі shared
scene, ground-truth TF, lifecycle readiness, арбітр teleop/Nav2 і cancel/hold.
Доступні B0/B1/IDW/GPR, causal live/replay, paired runner, reference evaluation.

Реальні Gazebo проїзди: об’їзд перешкоди з планом 5.98 м, досягнення цілі,
відхилення solid goal, скасування руху зі зупинкою, B1 RSSI recovery та ZIP.
Перевірено 7 paired configurations зі спільними 10 observations до втрати:
5 відновлень, 2 відмови без safe target. Окремо 5 світів × 2 Tx layouts:
B1 відновив RSSI у 9/10 випадків. Це пілоти, не статистична перевага.
Приклади, report/CSV/ZIP і графік — у examples/experiments/.

На 43 spatially held-out reference-точках за коротким префіксом (4 навчальні
точки після thinning) GPR мав високу помилку. Наявність GPR не означає
готової каліброваної моделі. Dataset split/convergence/валідація лишаються
обов’язковими для дослідницьких висновків.

Nav2 dependencies перевірені як офіційні apt packages у наявному
ROS-контейнері. Новий Dockerfile додає ті самі packages; окремий чистий
rebuild нової версії в цій хмарі не виконувався через обмежений диск/vfs.
На ноутбуці користувача попередня версія успішно будувалася з Dockerfile;
для цього оновлення потрібна нова збірка images.

Керування й обмеження: [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md).

Фінальна перевірка: 19 Python tests, включно з примусовим завершенням
native worker та створенням нової сцени; 5 повторів lifecycle checks пройшли.
Радіосцени ізольовані в процесах, збережені штатні LLVM оптимізації.
Після зменшення goal tolerance до 0.03 м / 0.05 rad B1 recovery у live check
відновився приблизно за 15 sim s з однієї спроби під’їзду. Фінальний
paired-пілот у examples використовує однаковий префікс із 10 observations
для першого рішення всіх 7 конфігурацій і зберігає implementation/config hashes.
