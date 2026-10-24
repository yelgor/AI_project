# Передача проєкту

Проєкт зараз має робочий 3D-конструктор, готові Sionna/Gazebo/Clearpath backend
та збір/експорт датасету. Власний радіодвижок або модель фізики Husky не писалися.

## Порядок читання

1. [README](../README.md): інсталяція, швидкий запуск і checks.
2. [USER_GUIDE.md](USER_GUIDE.md): керування конструктором, Tx/Rx та Husky.
3. [DATASET_GUIDE.md](DATASET_GUIDE.md): збір, формат, metadata й аналіз.
4. [TECHNICAL.md](TECHNICAL.md): архітектура, API, координати, обмеження й дебаг.
5. [DATA_COLLECTION_TASK.md](DATA_COLLECTION_TASK.md): конкретна наступна задача учасника.
6. [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md): подальша інтеграція Nav2, live/replay
   карт, режимів відновлення та порівняння B0/B1/IDW/GPR; це план, не наявні можливості.

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
коліс, груп doorway, RF-корпусу робота, packet PHY, GPR/Nav2 чи авторизації.
Ray tracing не доводить full-wave/real-world accuracy; потрібні convergence
checks і калібрування. Не підміняти пропуски/помилки нульовим RSSI.
