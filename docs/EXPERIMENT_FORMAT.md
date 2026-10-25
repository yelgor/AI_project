# Формат автономного експерименту та API

Це окремий формат від recording/grid із DATASET_GUIDE. Обидва збережені;
активний експеримент і окремий recording/grid одночасно не запускаються.

## ZIP v1

У `.runtime/experiments/<id>/` та ZIP із тим самим коренем:

- `manifest.json`: format_version=1, experiment_id, status, config, timestamps,
  scene_revision, scene_sha256, radio_field_sha256, software/navigation_software,
  implementation_sha256, navigation_config_yaml/navigation_config_sha256, solver_runtime,
  критерій RSSI proxy, ground-truth localization, metrics і reason.
  Додатково preparation та shadow_preflight: контрольні точки/покази,
  запас нижче порога і controller_training=false.
- `scenario.json`: нормалізована shared scene v2.
- `timeline.jsonl`: події з sequence, sim_time_s та kind.

Метри — world/map frame, вісь Z угору; кути — rad, потужність — dBm,
sim-time — секунди. Config route задає `[x,y,yaw_rad]`, на відміну від
scene.robot.position `[x,y,z]`. UI yaw показує градусами.

`scene_sha256` — повний snapshot включно зі spawn. `radio_field_sha256` —
канонічний JSON `{objects, tx, radio}` зі sorted keys/compact separators.
Він дозволяє порівняти reference і recovery після зміни spawn; орієнтацію
антени та висоту треба перевіряти окремо. Hash не означає фізичну точність.

## Події

| kind | Поля |
| --- | --- |
| pose | pose: position, quaternion_xyzw, sim_time_s, за наявності швидкості; navigation |
| observation | measurement: RSSI/SNR/CIR, позиція/орієнтація антени, robot_pose, sim_time_s, available_at_sim_time_s, observation_index |
| map | model_version, cells, training_indices, observation_count, fit_predict_wall_s, display_method, sigma_kind |
| target | target.base `[x,y,yaw]`, path, length_m, метод/β/поріг/model_version та прогноз або observation_index |
| route | target.base/path/length_m для заданого survey waypoint |
| mode | mode, reason, за переходів — pose; за завершення — metrics |
| shadow_arrival | goal, reason: очікування підтвердження втрати в цільовій зоні |

`map.cells[]`: position_m антени, base кандидата, mean_dbm, std_db,
lower_dbm. Для IDW std_db=null; у B0/B1 display_method=IDW, а рішення
використовують лише історію. training_indices посилаються на послідовність
усіх observations, а не тільки валідних; cap/spacing застосовано після неї.

sequence задає порядок подій. **Час вимірювання і час його готовності різні**:
measurement.sim_time_s фіксується перед розрахунком, available_at_sim_time_s
— за останньою отриманою world telemetry при завершенні розрахунку.
Подія observation та рішення за нею відбуваються за availability-time.
Це точність дискретної телеметрії, не безперервний hardware timestamp.
UTC в manifest потрібний для inventory, не для відновлення simulation clock.

Поза логуються приблизно кожні 0.2 sim s; карта — після нових вимірювань.
Відтворення показує останній доступний стан. Нового RSSI/моделі між подіями
немає. Карта в replay не переобчислюється за майбутніми observations.

Для paired history config.history_from посилається на інший завершений
експеримент. Seed observations мають seed_experiment_id і original_sim_time_s;
їх sim_time_s перенесено відносно нового старту, тому воно може бути від’ємним.
Уся ця історія доступна на початку нового recovery. Спостереження після
першого LINK_DEGRADED джерела не копіюються. Scene field, mount, spawn XY
і heading перевіряються до початку.

## Метрики

success=true лише для RECOVERED_WAIT. duration_sim_s — весь запуск,
recovery_time_s — від деградації до завершення (також для невдалих спроб),
path_length_m — накопичена 3D world distance, recovery_path_length_m —
тільки у RECOVERY. observation_count включає seed history, replans —
число спроб призначення recovery target. wall_duration_s — реальний час.
operator_interventions враховує явне скасування/повернення керування оператором;
нормальна телеоперація до втрати сюди не входить. Старі ZIP можуть не мати
цього поля або optional implementation/config metadata.
Ці величини не є packet statistics/contact counts.

Закриття backend позначає активний запуск INTERRUPTED; при аварії це
відбувається при наступному старті. Неповні/порожні metrics не доповнюються
вигаданими успіхами. На recovery зупинці runtime hold обнуляє привід.

## HTTP API конструктора (порт 8010)

| Метод і шлях | Тіло / відповідь |
| --- | --- |
| GET `/api/state` | Додатково navigation та experiment; останній поточний запуск або null |
| GET `/api/navigation/map` | Межі/розмір/resolution occupancy; localization/static flag |
| POST `/api/navigation/plan` | `{ "position": [x,y,yaw] }` → path, length_m |
| POST `/api/navigation/goal` | Те саме → план + запуск NavigateToPose |
| POST `/api/navigation/cancel` | `{}` → скасування action, припинення експерименту, повернення teleop |
| POST `/api/experiments/start` | config → manifest |
| POST `/api/experiments/stop` | `{}` → завершення й hold |
| GET `/api/experiments` | Усі manifests, найновіші першими |
| GET `/api/experiments/<id>` | manifest, scenario, timeline |
| GET `/api/experiments/<id>?after=SEQ` | Лише події після sequence; metadata лишається повною |
| GET `/api/experiments/<id>.zip` | Архів завершеного запуску |
| GET `/api/datasets/<id>` | Завершений grid/recording як manifest/scenario/measurements для viewer |

Config: method, beta, q_safe_dbm, hysteresis_db, degraded_s, stable_s,
timeout_s, stale_s, noise_db, optimize_gpr, bounds, grid_step_m, route,
label, pair_id, split (pilot/train/validation/test), history_from,
monitor_window_s, save_cir, require_shadow_loss, shadow_goal, shadow_radius_m.
monitor_window_s усереднює лінійну потужність за measurement.sim_time_s.
save_cir=false прибирає список paths, залишаючи точні coherent RSSI/path_count.
Межі й defaults див. `configuration()` у app/experiments.py та пілотний JSON.
Один активний запуск; immutable scene. Ліміти: 900 map cells, 30 waypoints,
150 spatially distinct GPR training points, 1 MiB request body.

Внутрішній supervisor Husky, порт 8766: `/start`, `/stop`, `/control`,
`/nav/plan`, `/nav/goal`, `/nav/cancel`, `/nav/hold`. Browser звертається до
8010. HTTP health supervisor не доводить readiness Nav2: перевіряється
активний lifecycle planner/controller/bt_navigator та наявність action servers.
Radio backend тримає кожну native/JIT сцену в окремому процесі; IPC передає
лише координати та plain-data результати. solver_runtime описує цю ізоляцію.
Runtime є єдиним паблішером команд цього застосунку до приводу; Nav2 Twist
і teleop проходять його arbitration. Node використовує simulation clock.

implementation_sha256 ідентифікує application/launch/navigation sources на
старті сервісу; після змін коду обидва сервіси потрібно перезапустити.
Параметри Nav2 зберігаються окремим YAML snapshot у manifest. Фактичні
версії ROS packages приходять від runtime. Це не bit-exact Gazebo snapshot.

Локальні bind-порти не мають авторизації. Це дослідницька інсталяція для
одного користувача, без безпечного multiuser deployment.

## Місії та серії

| Метод і шлях | Тіло / відповідь |
| --- | --- |
| GET `/api/missions` | Список доступних фізичних сценаріїв |
| GET `/api/missions/<name>` | scene і config обраного сценарію |
| POST `/api/mission/start` | `{mission:"shadow",layout:0,manual:false,config:{...}}` → async preparation |
| POST `/api/mission/stop` | `{}` → скасування підготовки/експерименту та hold |
| POST `/api/session/prepare` | `{scene:{...},reuse:true}` → cold/warm фізична підготовка, revision/epoch/profile |
| POST `/api/campaign/start` | `{runs:140,workers:2,methods:[...],betas:[0,1],protocol:"paired"}` або `{resume:"ID"}` |
| POST `/api/campaign/stop` | `{}` → запит cancellation, cleanup owned workers |
| GET `/api/campaign/state` | phase/progress/active_workers/recent/quality або null |
| GET `/api/campaigns` | Збережені manifests серій |
| GET `/api/campaigns/<id>.zip` | Завершена серія: reports, analysis, source/episode ZIP, attempts |
| GET `/api/campaign/worker/<0..3>/state` | Проксі live state конкретного воркера |

Серія живе в `.runtime/campaigns/<id>`. `attempts.jsonl` містить кожен завершений
task_index, включно із SETUP_FAILED/RUN_FAILED. `sources.json` зберігає checkpoint
парного протоколу, `source_attempts.jsonl` / `source_errors.jsonl` — всі вихідні спроби.
`analysis/` містить оцінку близькості й causal прогнозів; див. QUALITY.md.

Воркери: `.runtime/workers/<i>`, radio HTTP 8101+i, ROS runtime 8801+i,
ROS_DOMAIN_ID=50+i, GZ_PARTITION=radio-lab-worker-i. Це внутрішні порти контейнерної
мережі; браузер користується головним API. GUI-only клієнт може приєднатися до
конкретної partition. World pose містить robot_epoch та joint_positions;
старі epoch/revision/покази до reset відкидаються.
