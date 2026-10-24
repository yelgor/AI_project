# Radio Lab — 3D-конструктор радіоекспериментів із Husky

Побудуйте приміщення, розмістіть Tx/Rx у 3D, запустіть класичний
**Husky A200 Clearpath** та зберіть датасет. Радіофізику обчислює
**NVIDIA Sionna RT 2.2.0**, рух/зіткнення — **Gazebo Harmonic / ROS 2 Jazzy**.
Frontend — Three.js; власного розв'язувача радіохвиль немає.

## Запуск

Linux x86_64, Python 3.12/venv + LLVM/libatomic, Node.js 20.19+ або 22.12+,
Docker Engine + Compose v2. Потрібен вільний диск для кількох ГБ ROS-залежностей.
Повна інсталяція і мережеві prerequisites — [USER_GUIDE](docs/USER_GUIDE.md).

```bash
bash scripts/run_demo.sh
```

Браузерна адреса на локальній машині: `http://127.0.0.1:8010`.
Перший запуск будує образи; на підготовленій машині:

```bash
docker compose up -d --no-build
```

Під час старту готуються офіційні visual assets Husky. Після відкриття UI:
**Кімната → Tx/Rx → Застосувати сцену → Виміряти**.
Для руху: **Rx: Антена на Husky → Apply → Запустити Husky → WASD**.
Для даних: **Почати/завершити запис** або **Зібрати сітку → ZIP**.

Для автономної демонстрації: **Експерименти / Replay → Підготувати демо
відновлення → дочекатися Nav2: ready → Почати експеримент**.
Адреса: `http://127.0.0.1:8010/experiments.html`.
Після оновлення зі старої версії спершу виконати `bash scripts/run_demo.sh`:
потрібні нові Docker images з Nav2 та scikit-learn.

![3D-конструктор](docs/constructor.png)

## Що працює

- 3D viewport, gizmo/числові координати, повернуті стіни, реальний дверний проріз,
  матеріали, Save/Load JSON і п'ять шаблонів, включно зі складом/двором.
- Статичний 3D Rx або антена на Husky із full rigid transform.
- Один shared scenario для Three.js, Mitsuba/Sionna та Gazebo SDF.
- Офіційні Husky visual meshes у браузері й physical model/controllers у Gazebo.
- Run/Stop, ручне керування, world pose, RSSI/SNR/CIR, async grid/recording.
- Датасет: CSV, JSONL, snapshot сцени, manifest/версії/units, events і ZIP.
- Upstream Nav2: occupancy зі спільної сцени, автономні цілі, статичний об'їзд,
  ground-truth localization, арбітраж teleop/Nav2 та cancel/hold.
- Режими деградації/відновлення RSSI, B0/B1/IDW/GPR-zero/GPR-pathloss, μ−βσ.
- Live/replay: карти, невизначеність, часовий RSSI, траєкторія/ціль/маршрут,
  збережені рішення й окремий ZIP експерименту.
- Runner 10 пілотних умов, парний запуск зі спільної історії до втрати,
  reports CSV/JSON, spatial holdout MAE/RMSE/NLPD/coverage.

Радіомодель: coherent narrowband multipath із reflection/refraction/diffraction.
SNR — synthetic thermal noise model. Не моделюються modem PHY/packet loss,
протокольні затримки, RF-вплив корпусу Husky чи інші передавачі.
Recovery використовує RSSI proxy, статичні перешкоди й Gazebo ground truth;
це не перевірка пакетного зв'язку, SLAM або динамічного об'їзду.
Матеріали/бюджет трасування потребують калібрування й convergence checks;
працездатність не означає full-wave або real-world accuracy.

## Документація для наступного учасника

- [Керування конструктором](docs/USER_GUIDE.md)
- [Збір, формат і аналіз датасету](docs/DATASET_GUIDE.md)
- [Архітектура, API, координати та дебаг](docs/TECHNICAL.md)
- [Передача проєкту](docs/HANDOFF.md)
- [Наступна задача: зібрати датасет](docs/DATA_COLLECTION_TASK.md)
- [План автономних експериментів, карт і демонстрації](docs/EXPERIMENT_PLAN.md)
- [Запуск автономних експериментів і демонстрації](docs/EXPERIMENT_GUIDE.md)
- [Формат експерименту, часові події та новий API](docs/EXPERIMENT_FORMAT.md)
- [Готові результати, ZIP і графік для демонстрації](examples/experiments/README.md)
- [Перевірений стан і обмеження середовища](docs/simulation-stack.md)

Сценарії/дані у `.runtime/` не входять у Git. Передавайте свої JSON/ZIP окремо.
Приклади результатів перевірки — `examples/datasets/`.

## Перевірки

На запущеному конструкторі, послідовно, без власного активного датасету:

```bash
.venv/bin/python -m unittest discover -s tests -v
python scripts/check_api.py
python scripts/check_constructor_integration.py
python3 scripts/check_navigation_experiments.py
npm --prefix frontend run test:e2e
```

Інтеграційний тест застосовує demo room, запускає/рухає симульований Husky,
записує вимірювання та перевіряє world pose/mount/CSV/JSONL/ZIP.
Browser test редагує Rx.Z, збирає сітку на двох висотах і завантажує ZIP.
Navigation check реально об'їжджає перешкоду, відхиляє solid goal, виконує
B1 recovery та перевіряє causal timeline/ZIP. Другий browser test перевіряє
цей завершений експеримент у replay; спочатку виконати navigation check.
Для нього потрібен Chromium; default `/usr/bin/chromium`, можна задати
`PLAYWRIGHT_CHROMIUM_PATH`. Tests змінюють demo active scene.

## Радіочастина без Docker

Для static Rx/grid не потрібен робот:

```bash
bash scripts/setup_constructor.sh
.venv/bin/python app/builder.py --port 8010
```

Без husky service браузер повідомить про відсутні official visual assets
і покаже габаритну рамку. Radio/grid лишаються доступними.
Legacy CLI також збережений:

```bash
bash scripts/setup_radio.sh
.venv/bin/python app/radio.py --config config/room.json sample 2 2 1.2
```

## Логи і зупинка

```bash
docker compose logs -f radio husky
tail -n 100 .runtime/husky.log
docker compose down
```

Stop у UI завершує Gazebo й активний запис; container runtime лишається
готовим до нового Run. Закриття браузера не завершує весь стек.
Хмарна публікація не зберігає живі процеси: перевірте images і перезапустіть.
