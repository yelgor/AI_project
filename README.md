# AI_project — симуляція радіозв’язку та Husky

Проєкт використовує готові симулятори: **NVIDIA Sionna RT** для радіоканалу та
**Gazebo Harmonic / ROS 2 Jazzy / Clearpath Simulator** для середовища і Husky A200.
Власного радіодвижка тут немає. Наразі репозиторій містить налаштування та
smoke-перевірку Sionna; інтеграція з роботом ще не реалізована.

## Перевірка радіодвижка

Потрібні Python 3.11+ і системна бібліотека LLVM для CPU-бекенду Dr.Jit.
У хмарній машині перевірено Python 3.12 і наявність libLLVM 17/19.

```bash
bash scripts/setup_radio.sh
```

Скрипт створює `.venv`, встановлює Sionna RT 2.2.0 та запускає готовий
`PathSolver` на вбудованій 3D-сцені. Перевіряються скінченні ненульові
коефіцієнти імпульсної характеристики каналу (CIR). Повторний запуск перевірки:

```bash
MPLCONFIGDIR="$PWD/.cache/matplotlib" .venv/bin/python scripts/smoke_sionna.py
```

Для наявного virtualenv: `RADIO_VENV=/path/to/venv bash scripts/setup_radio.sh`.
Перевірка не доводить фізичної точності кожного ефекту: хоча параметри
дифракції й відбиттів увімкнені, вона перевіряє працездатність движка.

## Husky та середовище

Обрано офіційний [Clearpath Simulator, гілка Jazzy](https://github.com/clearpathrobotics/clearpath_simulator/tree/jazzy).
Інструкції та поточні обмеження — у [docs/simulation-stack.md](docs/simulation-stack.md).
Gazebo/Husky, графічний доступ, ROS-адаптер радіоканалу й синхронізація
геометрії між Gazebo та Sionna поки не налаштовані.
