# Повний каталог наявного функціоналу Radio Lab

Звірено з кодом після `c25e849`, 25 жовтня 2026 року. Цей файл інвентаризує
поточну реалізацію. Пояснення роботи й сценарій виступу —
[PRESENTATION_GUIDE](PRESENTATION_GUIDE.md). Початкові плани в інших файлах
не означають, що запланований у них функціонал уже реалізований.

Швидка навігація: [запуск](#1-запуск-і-середовище-виконання),
[конструктор](#2-3d-конструктор-середовища),
[радіоканал](#4-радіосимуляція), [Husky/Nav2](#5-husky-ros-і-навігація),
[модель](#6-модель-rssi-та-рішення), [протокол](#7-протокол-місії-та-обробка-відмов),
[UI](#8-відображення-та-аналіз-у-браузері), [дані](#9-датасети-серії-та-відтворюваність),
[HTTP API](#11-http-api-повний-перелік), [CLI](#12-cli-інструменти),
[межі реалізації](#15-чого-в-поточному-проєкті-немає).

## 1. Запуск і середовище виконання

| Можливість | Реалізація / використання |
| --- | --- |
| Повний локальний стек | Docker Compose: `radio` та `husky` |
| Підготовка host-оточення | `scripts/setup_radio.sh`, `scripts/setup_constructor.sh` |
| Збірка та запуск | `bash scripts/run_demo.sh` |
| Одразу запустити GPR-місію з 3D-картою | `bash scripts/run_demo.sh --start` |
| Старт без нового build | `python3 scripts/start_demo.py`, коли сервіси вже працюють |
| Вибір готового світу через CLI | `start_demo.py --mission shadow/office/warehouse/district/courtyard` |
| Очікування готовності | Radio API, потім Husky API; спільний deadline, retries GET при reset/неповній відповіді |
| Налаштування адрес/очікування | `start_demo.py --base`, `--husky-base`, `--wait-seconds` |
| Захист від повторного старту | Один POST; активна місія відхиляє новий старт; невідомий результат POST не повторюється автоматично |
| Ідентифікація власника файлів | `.env` з LOCAL_UID/LOCAL_GID; наявний `.env` зберігається |
| Запуск без вікон | Gazebo server + software-rendered browser підходять для headless перевірок |
| Штатний Gazebo GUI | `scripts/gazebo_gui.sh`, також `--worker INDEX`; потрібний Linux desktop/display |
| Повторний запуск готових образів | `docker compose up -d --no-build` |
| Завершення стеку | `docker compose down` |
| Журнали | Compose logs, `.runtime/husky.log`, логи воркерів, записи помилок у manifests/timeline |

Node/Vite потрібні для frontend build; готовий frontend обслуговує Python.
Радіобекенд використовує CPU LLVM. Застосунок не перемикається на CUDA/GPU
автоматично. Локальні теги образів не означають публікації їх на Docker Hub.
Свіжі образи на іншому ПК та інтерактивний Gazebo desktop треба перевіряти
на тому ПК; [VERIFICATION](VERIFICATION.md) розділяє виконані перевірки.

## 2. 3D-конструктор середовища

| Можливість | Що доступне |
| --- | --- |
| Пресети | Empty, room, corridor, warehouse, courtyard |
| Стіни та перешкоди | Box-об’єкти з центром X/Y/Z, розмірами й yaw |
| Дверна стіна | Три сегменти з фізичним прорізом між ними |
| Стеля й підлога | Геометрія зі зручним прозорим показом стелі |
| Редагування | Вибір у дереві/viewport, gizmo переміщення/повороту, числовий inspector |
| Операції | Додати, перейменувати, дублювати, видалити |
| Матеріали | Concrete, brick, plasterboard, wood, glass, metal |
| Радіотовщина | `thickness_m` для ITU slab-моделі матеріалу |
| Камера | Орбіта, панорама, zoom, весь світ, вигляд згори |
| Допоміжний показ | Прозорі стіни/стеля; зміни прозорості не змінюють фізику |
| Сценарії | Збереження/відкриття JSON, dirty draft, явне Apply |
| Валідація | Типи, finite координати, розміри, ID, матеріали, допустимі позиції й RF-бюджети |
| Спільна геометрія | Scene v2 → Three.js, Mitsuba mesh, Gazebo SDF collision/visual та Nav2 occupancy |
| Узгоджене Apply | Нова revision, скидання старих pose/показів; активну місію/збір спочатку треба завершити |
| Сумісність | Міграція початкового box-JSON без поля version до scene v2 |

Окремі пресети конструктора та готові mission-світи мають різні геометрії,
навіть коли обидва називаються «склад» чи «двір».

## 3. Передавач, приймач та координати

| Можливість | Що доступне |
| --- | --- |
| Tx | Один нерухомий передавач із world X/Y/Z та yaw/pitch/roll |
| Static Rx | Один приймач у заданій 3D-позиції, без запуску Husky |
| Mounted Rx | Приймач на Husky, body-relative mount position та orientation |
| Full rigid transform | World pose антени з position/quaternion робота та mount |
| Геометричний LoS | Перетин прямої Tx–Rx з об’єктами; діагностика, не заміна RSSI |
| Позначення у UI | Tx, Rx, напрямки/положення, actual Husky pose |
| Одиниці | Метри, Z-up; JSON-орієнтація `[yaw,pitch,roll]` у rad; quaternion `[x,y,z,w]` |
| Різні висоти дослідження | Static/grid Rx може бути на різних Z; Nav2 рухається у X/Y |

## 4. Радіосимуляція

| Можливість | Поточна реалізація |
| --- | --- |
| Розв’язувач | Sionna RT 2.2.0 PathSolver, Mitsuba/Dr.Jit CPU |
| Ефекти | Specular reflection, refraction, diffraction, edge diffraction |
| Інтерференція | Когерентна сума комплексних шляхів одного Tx |
| Антени | Масив 1×1, isotropic pattern, V polarization |
| Параметри каналу | Frequency, Tx power, bandwidth, noise figure |
| Чисельний бюджет | Max depth, samples per source, max paths per source, seed |
| Sampling | Одиничний запит, періодичний запис, траєкторія та 3D-grid |
| Результат | RSSI dBm, SNR dB, linear gain, число ненульових CIR коефіцієнтів |
| CIR | `real`, `imag`, абсолютний `delay_s` кожного ненульового коефіцієнта |
| Збереження CIR | Опційне в експерименті; вимкнення прибирає серіалізацію, зберігаючи точний coherent RSSI |
| Відсутній канал | `rssi_dbm=null`, `snr_db=null`, без вигаданого числового значення |
| Невалідна точка | Відхилення solid position або відстані до Tx <0.1 m |
| Стійкість backend | Окремий процес на радіосцену, послідовний доступ до solver, native crash containment |
| Кеш/потоки | Dr.Jit cache та обмеження CPU-потоків; штатна MergeFunctions оптимізація |
| Legacy CLI | `app/radio.py`: sample, trajectory, map PNG, serve, export-gazebo |

Bandwidth використовується для шумової оцінки SNR. Передавання бітів,
модуляція, demodulation, BER/BLER/PDR/throughput та завади інших Tx не реалізовані.
Стан RF-сцени статичний протягом експерименту; змінюється положення Rx.
Геометричне трасування не гарантує точного врахування всіх фізичних ефектів.

## 5. Husky, ROS і навігація

| Можливість | Що доступне |
| --- | --- |
| Офіційний робот | Clearpath A200 URDF, Gazebo physics/drive, collisions |
| Visual assets | Підготовка офіційних STL/COLLADA, 6 visual meshes у браузері, оригінальні матеріали |
| Телеметрія | Іменована world pose, quaternion, sim time, odometry velocities, joint angles |
| Старт/завершення | Власна process group Gazebo/ROS, поетапне завершення процесів |
| Warm reset | Спочатку brake, потім set_pose, нова epoch і перевірка settle; sim clock зберігається |
| Ручний рух | WASD/стрілки, екранні кнопки, прямий HTTP control |
| Арбітраж | Teleop / Nav2 / hold; ненульове ручне втручання не перезаписує активну автономію |
| Lease/deadman | Старі velocity-команди обнуляються; втрата backend скасовує автономний рух |
| ROS output | `TwistStamped` у `/a200_0000/platform/cmd_vel` |
| Nav2 | NavFn із A*, Regulated Pure Pursuit, lifecycle readiness, goal checker |
| Occupancy | Статична карта зі спільної геометрії, robot radius та inflation |
| Localization | Ground-truth map→odom; world pose взята з Gazebo |
| Планування | ComputePathToPose, досяжність, довжина маршруту |
| Виконання | NavigateToPose, status, cancel, hold, replanning після невдалої цілі |
| Шлях у UI | Пройдена траєкторія, запланований Nav2-шлях і обрана ціль |
| ROS радіоповідомлення | `/radio/measurement`, `std_msgs/String` із JSON |
| Старий ROS bridge | `app/ros_radio.py` існує для odom+spawn offset; не є основним world-pose pipeline |

Рух планується у 2D, хоча механічна симуляція та положення антени — 3D.
Немає налаштованого SLAM/AMCL, lidar obstacle layer для рухомих перешкод,
NN-контролера коліс, довільного robot-upload чи multi-robot координації.

## 6. Модель RSSI та рішення

| Можливість | Реалізація |
| --- | --- |
| B0 | Остання відома добра позиція |
| B1 | Найкоротший досяжний шлях до доброї виміряної позиції |
| IDW | Обернений квадрат відстані, точне відтворення у навчальній точці |
| GPR-zero | Нульовий prior, Matérn GP; діагностичний метод |
| GPR-pathloss | Least-squares тренд log-distance + GP residual |
| Online fit | Перерахунок за доступними спостереженнями при надходженні даних |
| Відбір даних | До 150 останніх spatially distinct точок, мінімум 0.15 m між відібраними |
| Виходи GPR | Mean μ, latent σ, training indices, model version і fit/predict wall time |
| Налаштування | Noise, optional kernel optimizer через config/API, β, q_safe |
| Правило цілі | `μ−βσ ≥ q_safe`, geometry mask, Nav2 reachability, shortest path |
| Методи без σ | B0/B1 показують IDW-карту; IDW не оцінює σ; β для них не допускається |
| Відомі невдалі цілі | Відхилення повторно невдалих recovery-кандидатів під час епізоду |
| Offline аналіз | Train/validation profile selection, spatial holdout, frozen test, learning-prefix curves |
| Python integration | `RadioMap(...).fit(observations).predict(points)` |

Немає NN-ваг, NN/RL training loop, model registry, load/save нейромережі,
endpoint `/api/model/predict` чи готового універсального plugin API.
Точки майбутньої інтеграції — [розділ 10 гайда](PRESENTATION_GUIDE.md#10-інтерфейс-моделі-та-майбутньої-нейромережі).

## 7. Протокол місії та обробка відмов

| Можливість | Що реалізовано |
| --- | --- |
| Готові місії | Shadow, office, warehouse, district, courtyard; дві Tx-конфігурації для кожної |
| Автоматичний виїзд | Фізичні Nav2 waypoint у напрямку перевіреної радіотіні |
| Ручна місія | Рух WASD із mounted Rx; у тому числі власна сцена конструктора |
| Preflight | Валідація anchor і чотирьох сусідів через Sionna/LoS, запас під порогом; не training input |
| Responsive-профіль | Крок sampling 0.25 s, brake на першому raw падінні, підтвердження 0.5 s |
| Підозра на втрату | LINK_SUSPECT; короткий провал можна переждати й продовжити маршрут |
| Обмеження очікування | Консервативне повернення після 2 s невизначеного сигналу, окрема причина |
| Фактичне гальмування | Odometry speed/yaw rate, quiet interval, brake timeout, подія `brake` |
| Повернення | LINK_DEGRADED → RECOVERY → RECOVERED_WAIT за RSSI-протоколом |
| Benchmark-профіль | Попередні 0.5 s sampling / 2 s filter / 1 s loss та anchor gate |
| Гістерезис | Окремі пороги погіршення й відновлення |
| Стійке відновлення | Raw/filtered RSSI та stable duration; hold і запис результату |
| Захист від дублів | Responsive не підтверджує події старими/повторними samples |
| Валідація RSSI | Відмова для нечислових/nonfinite значень перед додаванням до історії |
| Freshness/motion guards | Вік показу, зміщення від sample pose, свіжа Gazebo pose, reset epoch/revision |
| Зупинки при помилці | Solver error, stale data, немає досяжної цілі, timeout, непідтверджений brake |
| Відновлення після restart backend | Незавершений епізод позначається INTERRUPTED із подією в timeline |
| Причини/метрики | Sustained weak RSSI та verification timeout розрізняються; помилка не є success |

Повні стандартні пороги, sim/wall часи та семантика очікування —
[LINK_PROTOCOL](LINK_PROTOCOL.md). Повідомлення про успіх означає виконання
RSSI-критерію, а не виміряну PDR або гарантію якості каналу на майбутнє.

## 8. Відображення та аналіз у браузері

| Можливість | Де доступно |
| --- | --- |
| Live та prepared preview | Вкладка «Місія», з окремим позначенням джерела |
| Поточні покази | RSSI, LoS/NLoS, число observations, фаза, причина та помилки |
| Часовий графік | RSSI/monitor RSSI, поріг і дані до поточного replay-часу |
| Ground layers | Observations, mean, σ, μ−βσ |
| Об’ємна карта сигналу | RSSI як графічна висота над X/Y, увімкнена за замовчуванням |
| Регулятори поверхні | Амплітуда 5/10/16; повна шкала або ±20/±10 dB навколо q |
| Hover | Найближчий вузол surface: RSSI, X/Y і фізичний Z |
| Камери | Fit world із поверхнею, top, Husky close-up, orbit/pan/zoom |
| Fullscreen | Великий viewport; Stop доступний у live та вимкнений у replay |
| Recorded replay | Play/pause, reset to beginning, time slider, causal observations/maps/targets |
| Пошук записів | Scene, method, ID, status; локальний список прокручується окремо |
| Deep links | Відкрити конкретний local або curated run, layer і початкову фазу через URL |
| Архівні приклади без імпорту | Читання bundled ZIP у режимі лише перегляду |
| Reference overlay | Явний вибір після експерименту; RF-hash і Z перевіряються; не live input |
| Reference surface | Плоска чи 3D-карта для відповідного grid |
| Немає відповідного reference | UI не підставляє інше поле; responsive-demo має повідомлення про відсутню grid |
| Research dashboard | Навчальна крива, controls prefix/profile/scene, prediction/reference карти |
| Точковий аналіз | Прогноз/σ/reference/error та membership у fixed holdout |
| Результати | Test MAE/RMSE/coverage, profile tables, GPR denominators, safe-target checks |
| Аналіз невдач | Фільтри cohort/outcome/scene/ID, raw ZIP, 3D fail/repeat links |
| Докази ітерацій | Noise-порівняння, Nav2 corner plot, sensitivity дані та числові обмеження |
| Останні локальні GPR-записи | Відділення від відомих імпортованих curated ID |
| Завантаження | JSON/CSV/ZIP, графіки PNG, готові demo-відео серед матеріалів корпусу |

Відображення CIR означає числові коефіцієнти/затримки в даних. Повних
геометричних поліліній трасованих променів та анімації електромагнітної
хвилі в UI немає. Лінія Tx–Rx є LoS-діагностикою.

## 9. Датасети, серії та відтворюваність

| Можливість | Що зберігається/виконується |
| --- | --- |
| Static recording | Періодичні покази налаштованого Rx без робота |
| Husky recording | Вимірювання в actual antenna pose під час ручного руху |
| 3D-grid | Min/max/step X/Y/Z, фоновий перебір, прогрес і cancel |
| Пропуски | Solid/near-Tx позиції записуються як skipped, помилки — в events |
| Часткові результати | Cancelled/failed/interrupted датасети не підміняються completed |
| Dataset ZIP | Scene, manifest, measurements CSV/JSONL, events JSONL |
| Experiment ZIP | Scene, manifest, causal timeline JSONL |
| Час | Sim-time pose, availability-time measurement, UTC metadata; різні поля не ототожнюються |
| Структура provenance | Scene/RF hashes, версії software, implementation hash, Nav2 YAML/hash, solver runtime |
| Масові кампанії | 1–10 000 задач, 1–4 воркери, worker state/progress/stop |
| Ізоляція воркерів | Власні ROS domains, Gazebo partitions, порти та runtime directories |
| Full-протокол | Кожен епізод проходить виїзд, втрату й повернення |
| Paired-протокол | Спільний source prefix/checkpoint; кожне повернення виконується фізично в Gazebo |
| Перший paired-вибір | Фіксований causal prefix; свіжі покази не змінюють початкове порівняння |
| Повторне використання історій | `history_source_campaign`, зі звіркою умов |
| Warm reuse | Повторне використання світу/радіосцени і reset checkpoint |
| Resume | Продовження незавершених task indices, попередні результати залишаються |
| Звіти | Attempts, trials CSV, reports/analysis JSON, paired comparisons, campaign ZIP |
| Статистика | Успіх/невдача, Wilson intervals, time/path/replans/interventions, paired/bootstrap/McNemar |
| Оцінка карти | MAE/RMSE, false-safe, distance bins, coverage/NLPD там, де застосовно |
| Оцінка цілі | Окремий точний Sionna-запит у вибраній target position |
| Solver sensitivity | Порівняння budgets/depth/seed на зафіксованих точках |
| Імпорт прикладів | Dataset/experiment/campaign ZIP, bounds/path validation, без перезапису інших локальних даних |

## 10. Поточні обмеження обсягу

| Об’єкт | Межа у коді |
| --- | --- |
| Scene objects | До 100 |
| Об’єкт size | 0.01…1000 m на вісь |
| Scene координати | Скінченні, модуль до 10 000 m |
| RF frequency | 100 MHz…100 GHz; це допустимий діапазон вводу, не валідація точності на всіх частотах |
| Radio sample period | 0.2…60 s; фактичний крок може бути довшим |
| Depth | 0…8 |
| Rays / path budget | 100…1 000 000 |
| Static grid job | До 2 500 запланованих точок |
| Experiment map | До 900 XY-клітинок; step 0.3…3 m |
| Experiment route | До 30 waypoint |
| GPR/IDW training | До 150 spatially distinct точок |
| β | 0…5, лише GPR |
| Кампанія | 1…10 000 задач, 1…4 воркери |
| Збір в одній session | Один активний recording/grid/experiment; несумісні операції блокуються |

Ці межі не є гарантіями продуктивності. Більші RF-бюджети, сцени та число
воркерів збільшують CPU/RAM/диск і можуть зменшити фактичну частоту вимірів.

## 11. HTTP API: повний перелік

Основна адреса: `http://127.0.0.1:8010`. JSON POST має містити тіло, зокрема `{}`
для порожньої команди; максимальне тіло — 1 MiB. Довгі операції повертають
старт/стан, далі використовується polling. Авторизації та multiuser isolation немає.

### Читання

| GET | Результат |
| --- | --- |
| `/health` | Radio API status, backend, builder flag |
| `/api/state` | Scene/revision, robot pose/status, measurement, job/recording, mission, navigation, experiment/error |
| `/api/preset/<name>` | Empty/room/corridor/warehouse/courtyard scene |
| `/api/missions` | Список готових місій |
| `/api/missions/<name>` | Scene/config конкретної готової місії |
| `/api/navigation/map` | Metadata згенерованої occupancy-карти |
| `/api/datasets` | Manifests записів/grid |
| `/api/datasets/<id>` | Manifest, scene, measurements |
| `/api/datasets/<id>.zip` | Завершений/частковий dataset ZIP |
| `/api/experiments` | Локальні manifests, включно із записами воркерів |
| `/api/experiments/<id>` | Manifest, scene, timeline; підтримано `?after=SEQUENCE` |
| `/api/experiments/<id>.zip` | Архів завершеного епізоду |
| `/api/campaign/state` | Поточна серія/progress/workers/results |
| `/api/campaign/worker/<i>/state` | Проксі стану воркера 0…3 |
| `/api/campaigns` | Список campaign manifests |
| `/api/campaigns/<id>.zip` | Campaign ZIP |
| `/api/research` | Зведення опублікованих дослідів/моделей/прикладів |
| `/api/research/files/<allowed-file>` | Дозволений JSON/CSV/PNG/відео/ZIP доказів |
| `/api/research/runs/<cohort>/<id>` | Curated run прямо з архіву |
| `/api/research/runs/<cohort>/<id>.zip` | Raw ZIP цього run |
| `/api/research/references/<cohort>/<id>` | Відповідна reference grid за RF-hash, якщо існує |
| `/assets/husky/<file>` | Підготовлені visual assets та `model.json` |
| `/`, `/experiments.html`, `/research.html`, `/assets/...` | Зібраний frontend |

Curated cohorts: `baseline-100`, `gpr-tuned-20`, `navigation-30`,
`demo`, `gpr-demo`, `responsive-demo`. Довільний файл поза whitelist
через research API не читається. Офісний acceptance ZIP доступний серед allowed files.

### Команди

| POST | Тіло / дія |
| --- | --- |
| `/api/validate` | Scene → normalized JSON без Apply |
| `/api/scene` | Scene → застосування нової revision |
| `/api/session/prepare` | `{scene, reuse}` → cold start або warm prepare/reset |
| `/api/sample` | `{}` → configured static/mounted Rx |
| `/sample` | `{position_m:[x,y,z]}` → explicit sample, compatibility |
| `/api/robot/start` | `{}` → запуск фізичного Husky поточної сцени |
| `/api/robot/stop` | `{}` → завершення симуляції |
| `/api/robot/control` | `{linear,angular}` → ручні швидкості |
| `/api/robot/telemetry` | Внутрішній ingress pose/revision/epoch/velocities; у відповіді measurement |
| `/api/record/start` | `{}` → recording dataset |
| `/api/record/stop` | `{}` → завершення recording |
| `/api/grid/start` | `{min:[x,y,z],max:[x,y,z],step:[x,y,z]}` → grid job |
| `/api/grid/cancel` | `{}` → запит зупинки після поточного sample |
| `/api/navigation/plan` | `{position:[x,y,yaw],start?:[x,y]}` → шлях без руху |
| `/api/navigation/goal` | `{position:[x,y,yaw]}` → plan + goal; активний експеримент володіє керуванням |
| `/api/navigation/cancel` | `{}` → cancel/teleop; активний експеримент завершується CANCELLED |
| `/api/experiments/start` | Experiment config → початок на вже готовій сцені/роботі |
| `/api/experiments/stop` | `{}` → завершення та hold |
| `/api/mission/start` | `{mission,layout?,manual?,response_profile?,config?}` → prepare + preflight + readiness + experiment |
| `/api/mission/stop` | `{}` → cancel pending launch / stop experiment / hold |
| `/api/campaign/start` | Runs/workers/methods/betas/protocol/trials/resume/history-source config |
| `/api/campaign/stop` | `{}` → зупинка серії та cleanup власних воркерів |

HTTP 400 означає невалідні дані/стан; 404 — відсутній ресурс; GET worker failure
може повернути 503. POST unexpected failure повертає 500. Для перевірки передумов
користуйтесь `/api/state`; API не запускає паралельно несумісні операції.

### Внутрішній Husky supervisor

Порт 8766: GET health; POST `/start` із revision, `/reset` із revision,
`/stop`, `/control`, `/nav/plan`, `/nav/goal`, `/nav/cancel`, `/nav/hold`.
Також `/pool/start` із `{workers:N}` та `/pool/stop` керують внутрішніми
воркерами. Їхні ROS domains — 50…53, runtime ports — 8801…8804,
radio API ports усередині стеку — 8101…8104; звичайний UI читає стан через
основний API, а не вимагає публікації цих портів на host.
Це внутрішній рівень backend/runtime. Звичайний користувач працює через основний API.
ROS topics/actions та типи наведені у [гайді](PRESENTATION_GUIDE.md#6-рух-husky-та-команди).

## 12. CLI-інструменти

| Файл | Призначення |
| --- | --- |
| `scripts/run_demo.sh` | Setup/build/Compose; optional `--start` |
| `scripts/start_demo.py` | Чекання обох API та один старт responsive GPR-місії |
| `scripts/setup_radio.sh`, `setup_constructor.sh` | Python/RF залежності, Node frontend install/build |
| `scripts/start_husky.sh` | Підготовка robot/visual assets, старт runtime |
| `scripts/prepare_robot.py` | Clearpath setup і підтримуваний extras hook |
| `scripts/prepare_husky_assets.py`, `prepare_husky_visuals.py` | Офіційні meshes/transforms/materials |
| `scripts/prepare_world.sh` | Експорт базового світу для сумісного workflow |
| `scripts/gazebo_gui.sh` | Desktop Gazebo GUI, optional worker |
| `scripts/run_experiments.py` | Full/paired, methods/betas/repeats, workers/runs, cold, resume, reuse history |
| `scripts/load_example_runs.py` | Перевірений імпорт example archives |
| `scripts/collect_reference.py` | Grid reference через API: bounds/height/step/output |
| `scripts/expand_reference.py` | Reference полів кампанії на кількох висотах |
| `scripts/evaluate_radio_maps.py` | Map scores для experiment/reference на заданому `--at` sim time |
| `scripts/study_reference.py` | Train/validation selection і frozen-test scores |
| `scripts/build_learning_evidence.py` | Reconstructed prefix fits/learning curves із bundled source/reference |
| `scripts/evaluate_targets.py` | Точна післяекспериментна перевірка обраних recovery goals |
| `scripts/analyze_campaign.py` | Campaign quality/forecast/causality analysis |
| `scripts/compare_campaigns.py` | Зіставлення matched pairs, success/time/path differences |
| `scripts/plot_campaign.py`, `plot_experiments.py` | PNG зведень |
| `scripts/plot_field.py` | Карти prediction/reference та помилок |
| `scripts/plot_navigation_fix.py` | Геометрична діагностика corner clearance |
| `scripts/validate_missions.py` | Перевірка геометрії/радіотіні готових місій |
| `scripts/check_convergence.py` | Чутливість solver до бюджету, depth та seed |
| `scripts/smoke_sionna.py` | Мінімальний ненульовий CPU CIR |
| `scripts/check_api.py`, `check_husky.py` | API/RF та Husky інтеграція |
| `scripts/check_constructor_integration.py` | World pose, mount, motion, dataset export |
| `scripts/check_reset.py` | Гальмування та фізичний warm reset |
| `scripts/check_navigation_experiments.py` | Nav2 detour, invalid goals, cancel, recovery і журнал |
| `app/builder.py` | Основний HTTP/static server, host/port/runtime CLI |
| `app/radio.py` | Legacy standalone radio CLI/API |
| `app/ros_radio.py` | Legacy ROS odom-to-radio adapter |

Конкретні аргументи перевіряються через `--help`; запуск integration/check
скриптів може змінити сцену та рухати симульований робот. Їх запускають
послідовно після завершення власного активного збору.

## 13. Де лежить реалізація

| Модуль | Відповідальність |
| --- | --- |
| `app/scenario.py` | Scene schema, validation, presets, quaternion/rigid transforms |
| `app/radio.py`, `app/engine.py` | Sionna adapter, geometry export та процесна ізоляція |
| `app/builder.py` | Session, HTTP, sampler, lifecycle, grid/record integration |
| `app/navigation.py` | Geometry clearance й static occupancy export |
| `app/husky_runtime.py` | ROS node, own Gazebo processes, telemetry, arbiter/actions/deadman |
| `app/radio_maps.py` | B0/B1 display, IDW/GPR fitting/prediction |
| `app/experiments.py` | Causal closed loop, loss/brake/recovery, target selection, timeline/metrics |
| `app/missions.py` | Mission worlds/configs, response profiles, LoS diagnostic |
| `app/campaigns.py`, `app/runtime_pool.py` | Scheduling, workers, warm reuse, paired/full/resume |
| `app/datasets.py` | CSV/JSONL/manifest/ZIP, field hash |
| `app/evidence.py` | Readonly published evidence/archives/reference access |
| `app/provenance.py` | Implementation fingerprint |
| `frontend/src/main.js` | Конструктор |
| `frontend/src/experiments.js` | Місії, серії, replay, control UI |
| `frontend/src/mission-view.js`, `signal-surface.js` | Official model rendering, actual pose, layers/3D surface |
| `frontend/src/research.js` | Learning/evaluation dashboard |
| `launch/`, `config/` | ROS/Gazebo/Nav2 launch та спільні/robot/mission параметри |

## 14. Готові матеріали та перевірки

У [shadow-benchmark](../examples/experiments/shadow-benchmark/README.md):
100 baseline + 20 tuned + 30 navigation paired-повернень, десять повних
source-місій, 7 356 reference позицій на трьох висотах, метрики/CSV/JSON,
raw ZIP, hashes, PNG та demo-відео. Окремо збережені B1 demo, повна GPR demo
і дві responsive acceptance-перевірки. Їх не додають до старих знаменників.

Python regression охоплює геометрію, coherent RF, native worker failure,
збір/архіви, fit/predict, causal replay, paired prefix, responsive braking,
стартові transport errors та provenance. Node checks перевіряють surface
geometry/масштаб без зміни даних. Playwright перевіряє UI, official Husky,
власну кімнату/mount, фізичну місію, fullscreen та readonly дослідження.
Факти виконання й команди — [VERIFICATION](VERIFICATION.md).

## 15. Чого в поточному проєкті немає

| Напрям | Поточний стан |
| --- | --- |
| Нейромережа/навчені NN-ваги | Не реалізовані; прогнозує GPR |
| RL або навчена policy об’їзду | Не реалізовані; керує Nav2 |
| QAM/OFDM/coding/BER/PDR/MAC | Не реалізовані; є channel/CIR/RSSI/SNR |
| Multi-Tx/interferers/MIMO experiments | У application workflow один Tx/Rx |
| RF-вплив корпусу Husky | Не входить у Sionna geometry |
| Повнохвильовий Maxwell solver | Не використовується |
| Підтверджена апаратна точність | Немає польового датасету/валідації фізичного Husky |
| CAD/довільний mesh import | Немає; official robot assets не є загальним importer світу |
| Стінові roll/pitch, terrain/DEM editor | Немає у конструкторі; підтриманий yaw boxes |
| Живі рухомі стіни/перешкоди | Немає узгодженого dynamic RF/world workflow |
| SLAM/AMCL/динамічний lidar avoidance | Не налаштовані в поточній навігації |
| Геометричний ray-path renderer | Немає; у даних CIR coefficients/delays, не повні сегменти трас |
| Загальне завантаження роботів/NN plugins | Немає готового універсального інтерфейсу |
| Multiuser/auth | Немає; локальний лабораторний стек |
| Повністю immutable OS/container lock | ROS tags/apt можуть змінюватись; manifests записують фактичні версії |

Ці пункти треба представляти як можливості подальшого розвитку, а не як
вже показаний на презентації результат.
