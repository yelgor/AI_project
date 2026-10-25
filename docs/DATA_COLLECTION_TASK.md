# Наступному учаснику: розширити й перевірити датасет

Готові фізичні shadow-місії, серії 100+ та оцінювання: [QUALITY.md](QUALITY.md).
Почніть із відтворення [DEMONSTRATION.md](DEMONSTRATION.md), потім додавайте
нові геометрії до зафіксованого набору. Нижче — вимоги до нових незалежних сцен.

## Мета

За допомогою готового конструктора зібрати відтворювані сцени, повні grid-карти
і розріджені вимірювання на маршрутах Husky для майбутнього GPR/IDW.
Спочатку прочитати USER_GUIDE.md та DATASET_GUIDE.md, виконати README checks.

## Робота

1. Перевірити інсталяцію на своїй машині; зберегти версії/помилки, якщо щось
   не відтворюється. Після запуску перевірити кімнату, Rx.Z та рух Husky.
2. Побудувати мінімум 6 сценаріїв: порожня сцена, кімната та коридор,
   кожна з двома розміщеннями Tx. Для всіх зберегти scenario JSON.
3. На кожній сцені зібрати grid до 338 позицій на двох висотах; межі
   адаптувати до вільного простору, матеріали й radio settings фіксувати.
4. У кімнаті/коридорі записати кілька маршрутів Husky через видиму ділянку,
   поворот/прохід і радіотінь. Під час одного порівняння не змінювати mount/frequency.
5. Для кількох точок перевірити convergence: більші samples/max_depth.
   Seed — параметр чисельного path search, а не фізичний fading.
6. Перевірити кожен ZIP: counts, errors, null RSSI, units, revision,
   motion/antenna positions та hashes. Не вважати нуль рядків успішним збором.
7. Скласти inventory CSV і короткий звіт зі схемами сцен, умовами збору,
   бюджетами трасування та виявленими обмеженнями.

## Передати команді

- JSON кожного сценарію;
- ZIP датасетів зі scene snapshot, manifest, CSV/JSONL/events;
- inventory CSV із dataset_id, scene name, Tx layout, kind, counts, split;
- 2–3 приклади spatial RSSI plots і одного Husky trajectory;
- окремо spatial/scene train-validation-test split та список convergence checks.

Повна grid-карта — симуляційний reference; маршрут або її підвибірка — sparse
observations. Не змішувати різні Tx/сцени в одне поле без відповідної моделі.
Не вигадувати packet loss/latency: цих величин поточний симулятор не генерує.

## Наступні coding-задачі після збору

GPR/IDW, Nav2 RSSI recovery і live/replay вже реалізовані; використання та
runner — у [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md).
Подальші coding-задачі: ROS typed measurement message, calibrated modem PHY,
mesh/CAD import, grouping doorway segments, RF-вплив корпусу робота, багатокористувацький захищений deployment та CI fresh-build.
Це розширення, а не вимоги до вже наявного пилотного конструктора.
