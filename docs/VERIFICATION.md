# Перевірений стан, 25 жовтня 2026

- Python: 44 tests, 43 pass та один ROS-only skip на host.
- ROS-only serialization regression окремо пройшла в sourced Husky container.
- HTTP API: дві 3D точки, ненульовий CIR та відмова для solid-position.
- Constructor integration: world pose, повний 3D mount, 0.749m фізичного руху,
  3 measurement rows, CSV/JSONL/ZIP під час цієї перевірки.
- Moving checkpoint reset: зупинка після ненульових linear/angular команд,
  warm pose reset <0.06m від spawn, simulation clock не скидався.
- Nav2 regression після зміни inflation/lookahead: фізичний об’їзд 6.91m,
  відхилення solid goal, cancel/гальмування, recovery, causal timeline та ZIP.
- Playwright: 4 acceptance checks — конструктор/3D grid,
  official Husky/replay/reference, повна фізична місія однією кнопкою,
  запуск власної кімнати зі збереженим Tx та нестандартним 3D mount Rx.
  Тест власної сцени також фізично рухає Husky через WASD і перевіряє Stop.
- Frontend production build, Python compile, shell syntax та git diff checks пройшли.
- 100 + 20 + 30 фізичних recovery запусків і 10 повних source-місій;
  підсумки й обмеження — [у корпусі](../examples/experiments/shadow-benchmark/README.md).

## Навчання, звіт і 3D висоти RSSI

- Повторно обчислено GPR noise 2 / noise 8 та IDW для 7 префіксів кожного
  з 8 train/validation полів. Фіксований holdout виключає сусідів навіть
  майбутніх для раннього кадру показів. Courtyard test не використано для кривих.
- Нові Python checks звіряють графіки з фактичним повторним fit, source/code
  SHA256, збереження невдач, тотожність seed RSSI/позицій зі зміщенням clock,
  правильні GPR-знаменники, доступ до архівів і відповідність еталонного RF-поля.
- Node: 4 перевірки геометрії RSSI-поверхні — скінченні обмежені висоти,
  null/ізольовані покази, відсутність зшивання крізь тонкі стіни,
  між віддаленими ділянками та різними фізичними висотами антени.
- Playwright: 5 перевірок звіту/readonly replay/3D поверхні пройшли разом
  після завершальних змін. Перевірено JSON/CSV/ZIP завантаження, невдачі,
  префікси, масштаби, архівний еталон без імпорту, відсутність команд руху
  з replay, перехід зі звіту до повної GPR-місії та повернення на початок.
- Окремий live acceptance пройшов повний GPR β=1 виїзд у Gazebo з оновленням
  RSSI-поверхні під час руху: NLOS loss, `RECOVERED_WAIT`, 113 вимірювань,
  17.10 sim s / 6.65 m recovery, 0 втручань. Raw запис —
  [gpr-demo.zip](../examples/experiments/shadow-benchmark/gpr-demo.zip).
  Візуальне вписування камери перевірене повторним readonly браузерним тестом.
  Це додатковий demo, не новий результат у 150-епізодному benchmark.
- [Екран аналізу](model-evidence.png), [3D-карта еталонного RSSI](radio-heightmap.png),
  [керування й протокол](MODEL_EVIDENCE.md).

## Посилена карта й раннє гальмування

- Геометрія поверхні: 5 Node checks, включно з точним множником реакції
  висоти 4× / 8× та незмінністю raw RSSI при перемиканні масштабу.
- Нові Python checks: перший слабкий показ гальмує до fit/вибору цілі;
  віддалений anchor не блокує реакцію; підтверджена швидкість перед Nav2 goal;
  одиничний провал, дублі, відсутня швидкість, невалідний RSSI, надмірне
  переміщення без показу й помилка розв’язувача.
  Окремо перевірене обмеження очікування 2 s у гістерезисному проміжку.
- Повний Playwright прогін 9 перевірок пройшов: старий benchmark-проїзд,
  ручна власна сцена, швидкий GPR-проїзд, аналіз/replay та fullscreen.
  Після додавання архіву швидкого проїзду окремо перевірені 7 readonly сценаріїв,
  включно з переходом зі звіту до нового протоколу без чужого еталону.
- Швидка GPR-місія `20261025T124848Z-bf0a13e6`: 139 показів,
  гальмівне зміщення 0.288 m, speed у `brake` 0.006 m/s,
  перша реакція за 7.45 m до anchor, повернення 11.20 sim s / 1.53 m.
- CLI `scripts/start_demo.py --mission office` фактично запустив другу
  місію `20261025T125034Z-5451028b`: 131 показ, 0.288 m / 1.60 sim s гальмування,
  повернення 11.35 sim s / 1.72 m. Обидві без operator interventions.
- Raw ZIP та контрольні метрики: [швидкий протокол](../examples/experiments/shadow-benchmark/responsive-demo-verification.json).
  Нові проїзди не змінюють старі benchmark-підсумки.

## Відтворити checks

Сервіси мають працювати; власний активний запис спочатку завершіть.
Тести змінюють демонстраційну сцену. Виконуйте послідовно:

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/check_api.py
python3 scripts/check_constructor_integration.py
python3 scripts/check_reset.py
python3 scripts/check_navigation_experiments.py
npm --prefix frontend run test:e2e
node --test frontend/tests/signal-surface.test.mjs
```

ROS regression:

```bash
docker compose exec husky bash -c 'source /opt/ros/jazzy/setup.bash; cd /project; python3 -m unittest discover -s tests -p test_ros_runtime.py -v'
```

Browser check потребує Chromium (`PLAYWRIGHT_CHROMIUM_PATH` може змінити шлях).
За замовчуванням video recording вимкнений, тож додатковий Playwright ffmpeg
для звичайних тестів не потрібний. Відео повної перевірки додане до корпусу.

Хмарний запуск headless: Gazebo server, ROS/Clearpath/Nav2, Sionna та browser
перевірені фактично. Desktop `gz sim -g` helper перевірений за shell syntax;
інтерактивний X11/Wayland desktop у cloud не перевірявся. Свіжий Docker build
на іншій машині треба перевірити окремо; поточне середовище використовувало
наявні образи з перевіреними залежностями. Версії пакетів є в manifests.

Попередній портативний імпорт корпусу в чистий runtime відновив рівно 161 experiment
(150 recovery + 10 source + demo), 10 grid datasets і 3 campaigns.
CRC всіх curated ZIP перевірено.
Після цього доданий окремий `gpr-demo.zip`, що дає ще один completed experiment;
його імпорт у чистий каталог перевірений окремо.
