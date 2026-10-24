# Передача проєкту

Проєкт має 3D-конструктор, Sionna/Gazebo/Clearpath, Nav2, збір датасету,
RSSI recovery B0/B1/IDW/GPR, live/replay і runner. Власний радіодвижок,
фізика Husky або планувальник шляху не писалися.

## Порядок читання

1. [README](../README.md): інсталяція, швидкий запуск і checks.
2. [USER_GUIDE.md](USER_GUIDE.md): керування конструктором, Tx/Rx та Husky.
3. [DATASET_GUIDE.md](DATASET_GUIDE.md): збір, формат, metadata й аналіз.
4. [TECHNICAL.md](TECHNICAL.md): архітектура, API, координати, обмеження й дебаг.
5. [DATA_COLLECTION_TASK.md](DATA_COLLECTION_TASK.md): конкретна наступна задача учасника.
6. [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md): автономна демонстрація,
   налаштування/навчання методів, парні експерименти, оцінка reference.
7. [EXPERIMENT_FORMAT.md](EXPERIMENT_FORMAT.md): новий формат журналу та API.
8. [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md): початковий план і критерії дослідження.

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
world pose + full antenna quaternion. Немає CAD/mesh import, анімації web
коліс, груп doorway, RF-корпусу робота, packet PHY чи авторизації.
Навігація використовує ground-truth localization і статичну occupancy;
динамічні перешкоди, SLAM/AMCL та реальний modem link не перевірені.
Ray tracing не доводить full-wave/real-world accuracy; потрібні convergence
checks і калібрування. Не підміняти пропуски/помилки нульовим RSSI.
