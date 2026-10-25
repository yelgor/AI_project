# Передача проєкту

Проєкт має 3D-конструктор, Sionna/Gazebo/Clearpath, Nav2, збір датасету,
RSSI recovery B0/B1/IDW/GPR, live/replay і runner. Власний радіодвижок,
фізика Husky або планувальник шляху не писалися.

Готовий корпус: [shadow-benchmark](../examples/experiments/shadow-benchmark/README.md)
із 150 physical recovery, 10 повними source-місіями, reference, відео й усіма
невдачами. [ITERATIONS.md](ITERATIONS.md) пояснює, що виявлено й виправлено.

## Порядок читання

Для загальної картини почніть із [PRESENTATION_GUIDE](PRESENTATION_GUIDE.md):
радіофізика, світ, команди, навчання GPR, інтеграція наступної моделі та сценарій
показу. [FEATURE_CATALOG](FEATURE_CATALOG.md) окремо інвентаризує поточний
функціонал і всі API; незавершені можливості явно позначені.

1. [README](../README.md): інсталяція, швидкий запуск і checks.
2. [DEMONSTRATION.md](DEMONSTRATION.md): запуск місії однією кнопкою та всі елементи керування.
3. [QUALITY.md](QUALITY.md): deliberate shadow, 100+ епізодів, full/paired, оцінка й ітерації.
4. [USER_GUIDE.md](USER_GUIDE.md): керування конструктором, Tx/Rx та Husky.
5. [DATASET_GUIDE.md](DATASET_GUIDE.md): збір, формат, metadata й аналіз.
6. [TECHNICAL.md](TECHNICAL.md): архітектура, API, координати, обмеження й дебаг.
7. [DATA_COLLECTION_TASK.md](DATA_COLLECTION_TASK.md): конкретна наступна задача учасника.
8. [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md): автономна демонстрація,
   налаштування/навчання методів, парні експерименти, оцінка reference.
9. [EXPERIMENT_FORMAT.md](EXPERIMENT_FORMAT.md): новий формат журналу та API.
10. [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md): початковий план і критерії дослідження.

Офіційна 3D-модель використовує реальні joint states коліс. Серії мають
1–4 ізольовані Gazebo/ROS воркери, warm reset, ZIP/звіти та resume.

## Передати разом із репозиторієм

Свої scenario JSON і ZIP потрібних датасетів. `.runtime/`, установлені
залежності, frontend/dist, Docker images та живі процеси не входять у Git.
README scripts створюють/відновлюють їх. Локальні Docker tags не означають,
що образи опубліковані на Docker Hub.

## Baseline наступного розробника

Відтворити Python tests, HTTP check, full constructor integration і browser
check послідовно. Інтеграційні checks змінюють демонстраційну сцену й рухають
тільки симульований робот; не запускати при власному активному записі.
Свіжий build на іншій машині треба перевірити окремо: поточна хмарна
машина використовує підготовлені/перевірені залежності й образи.

## Межі поточного етапу

Один Tx/Rx/Husky, box walls із yaw, підтриманий URDF extras PosePublisher,
world pose + full antenna quaternion. Немає CAD/mesh import, груп doorway, RF-корпусу робота, packet PHY чи авторизації.
Навігація використовує ground-truth localization і статичну occupancy;
динамічні перешкоди, SLAM/AMCL та реальний modem link не перевірені.
Ray tracing не доводить full-wave/real-world accuracy; потрібні convergence
checks і калібрування. Не підміняти пропуски/помилки нульовим RSSI.

Окремий перевірений стан і команди приймальних тестів: [VERIFICATION.md](VERIFICATION.md).
