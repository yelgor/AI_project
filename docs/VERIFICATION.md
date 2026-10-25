# Перевірений стан, 25 жовтня 2026

- Python: 29 tests, 28 pass та один ROS-only skip на host.
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

Портативний імпорт корпусу в чистий runtime відновив рівно 161 experiment
(150 recovery + 10 source + demo), 10 grid datasets і 3 campaigns.
CRC всіх curated ZIP перевірено.
