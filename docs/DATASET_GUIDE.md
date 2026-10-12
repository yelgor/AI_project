# Збір та формат датасету

## Два способи збору

### 3D-сітка: повне симуляційне поле

1. Побудуйте/завантажте сцену та Apply. Завершіть Husky: grid працює зі
   статичною геометрією й не запускається одночасно з ним або записом.
2. У панелі «Сітка у 3D» задайте min/max та step для кожної осі.
3. Наприклад: min `[-3,-3,1]`, max `[3,3,1.5]`, step `[0.5,0.5,0.5]`:
   це 13×13×2=338 запланованих точок на двох висотах.
4. Натисніть «Зібрати сітку», дочекайтесь `completed` і завантажте ZIP.
5. Для одного горизонтального шару задайте однакові min.Z/max.Z.

Кроки мають бути позитивними. Якщо інтервал не ділиться на крок, остання
точка буде меншою за max; solver не екстраполює за межу. Ліміт — 2500
запланованих точок на job. Точки у solid стінах або надто близько до Tx
пропускаються з поясненням у `events.jsonl`. Досягнення каналу не гарантоване:
валідна точка без знайдених шляхів записується з RSSI/SNR `null`.

«Скасувати» зупиняє перебір після поточного обчислення. Частковий датасет
зберігається як `cancelled`, а не підміняється повним.

### Запис: траєкторія Husky або статичний Rx

1. Для траєкторії оберіть Rx «Антена на Husky», Apply, Run і дочекайтесь running.
2. Натисніть «Почати запис» та пройдіть маршрут вручну.
3. Натисніть «Завершити запис», потім завантажте ZIP.
4. Для static Rx та сама кнопка періодично вимірює задану точку без робота.

Період задається radio.period_s. Це цільовий мінімальний інтервал між
запусками solver; при повільному обчисленні реальна частота нижча.
Не підставляйте фіксований timestep у аналіз: використовуйте записаний час.
Повторення static вимірювань у незмінній сцені детерміновані й не створюють
нових незалежних просторових прикладів чи штучного fading/noise.

Apply і новий grid заблоковані під час збору; завершення Husky також
завершує запис. Кожен старт створює новий dataset_id, файли не перезаписуються.
Невдалий запит пишеться в events, а не як вигаданий числовий RSSI.

## ZIP та файли на диску

Один архів містить каталог `<dataset_id>/`:

| Файл | Вміст |
| --- | --- |
| `scenario.json` | Точний canonical scene v2 для відтворення |
| `manifest.json` | Статус, counts, час, units, SHA256 сцени, версії Sionna/Mitsuba/Dr.Jit/NumPy, параметри grid |
| `measurements.jsonl` | Один повний вимір на рядок, включно з CIR, pose та quaternion |
| `measurements.csv` | Плоскі поля для pandas/таблиць |
| `events.jsonl` | Пропуски, помилки та команди керування під час запису |

На диску: `.runtime/datasets/<dataset_id>/`. У UI показані 8 останніх
датасетів; повний список доступний через `GET /api/datasets` та каталоги
на диску. ZIP доступний лише після завершення/скасування збору.

Статуси: `collecting`, `completed`, `cancelled`, `failed`, `interrupted`.
`completed` означає завершений процес збору, а не гарантію якості даних.
Обов'язково перевіряйте sample_count, skipped_count, error_count і null RSSI.
Порожній/частковий датасет не вважайте повною картою.

## Поля вимірювання

| Поле JSONL | Значення |
| --- | --- |
| `dataset_id`, `sample_index` | Ідентифікатор експерименту та індекс від 0 |
| `timestamp_utc` | UTC час збереження після обчислення; ISO 8601 |
| `scene_revision` | Активна редакція сцени, одна для цього датасету |
| `source` | `grid`, `static`, `husky` або `manual` |
| `position_m` | Фактичний Rx/antenna у world, [x,y,z] |
| `orientation_rad` | Орієнтація Rx у world: [yaw,pitch,roll] |
| `tx_position_m` | Положення передавача |
| `rssi_dbm`, `snr_db` | Вузькосмугова потужність та thermal-noise SNR; null при відсутності шляхів |
| `path_gain_linear`, `path_count` | Когерентний gain та кількість ненульових CIR коефіцієнтів |
| `paths` | Масив {real, imag, delay_s}; затримки абсолютні, секунди |
| `sim_time_s` | Час Gazebo pose для husky; null для static/grid |
| `robot_pose` | World position/quaternion та остання odometry velocity; null для static/grid |

CSV розкладає координати у `tx_x_m..tx_z_m`, `rx_x_m..rx_z_m`, орієнтацію
у `rx_yaw_rad/rx_pitch_rad/rx_roll_rad`. Для Husky є `robot_x_m..robot_z_m`,
`robot_qx/qy/qz/qw`, `linear_x/y/z_mps`, `angular_x/y/z_radps`.
CIR залишається тільки в JSONL. Null у CSV — порожня клітинка.

Поза робота й антени — world frame, Z-up. Швидкості з odometry — body/base_link
frame, не world; вони можуть бути відсутні у перших повідомленнях.
Robot quaternion має порядок [x,y,z,w]. Час pose може бути раніше за UTC
збереження на тривалість обчислення solver. ROS sim time може обнулитися
при новому Run; не з'єднуйте записи різних запусків лише за цим часом.

`manifest.scene_sha256` — SHA256 JSON із sort_keys=True та separators=(',',':'),
а не hash байтів pretty-printed файлу. Сценарій включає radio settings і seed.
Visual meshes Husky до архіву не копіюються: для запуску потрібен Clearpath.

## Приклад аналізу

Після розпакування ZIP (pandas — опційна залежність для аналізу):

```python
from pathlib import Path
import json
import pandas as pd

folder = Path('path/to/extracted/dataset-id')
manifest = json.loads((folder / 'manifest.json').read_text())
data = pd.read_csv(folder / 'measurements.csv')
assert len(data) == manifest['sample_count']
print(manifest['status'], manifest['skipped_count'], manifest['error_count'])
valid = data.dropna(subset=['rssi_dbm'])
X = valid[['rx_x_m', 'rx_y_m', 'rx_z_m']].to_numpy()
y = valid['rssi_dbm'].to_numpy()
```

Не перетворюйте null на 0 dBm. Якщо для моделі потрібен «немає зв'язку»,
введіть окреме правило censoring/поріг і збережіть його у протоколі аналізу.
SNR у цій моделі обчислений із RSSI та noise floor, тому не є незалежним виміром.

## Рекомендований перший протокол

1. Відтворити порожній простір, кімнату й коридор; зберегти JSON кожної сцени.
2. Для кожної зробити два положення Tx — 6 сценаріїв із зрозумілими назвами.
3. Для кожного зібрати grid до 338 точок, перевірити доступний простір,
   counts/errors і відтворюваність. За потреби скоригувати bounds під геометрію.
4. У кімнаті та коридорі записати кілька маршрутів Husky, включаючи ділянки
   за перешкодою. Зберігати spawn, mount і радіопараметри незмінними в межах порівняння.
5. На кількох контрольних точках збільшити samples/max_depth та оцінити
   збіжність. Seed змінює чисельний sampling solver, а не матеріали чи фізичний шум.
6. Скласти inventory CSV: dataset_id, scene name, Tx layout, kind, row counts,
   null/error counts, призначення train/validation/test.

Для GPR/IDW тримайте повну grid-карту як ground truth, а маршрут/підвибірку
— як sparse training observations. Виділяйте просторові області/цілі сцени
для перевірки: випадкове розділення сусідніх точок може дати завищену якість.
Дані різних геометрій/Tx не є одним полем без додаткових ознак/моделі.

Це симуляційний ground truth конкретного ray tracer. Немає modem packet
success, затримки протоколу, сторонніх передавачів або виміряного receiver
noise. Їх не слід приписувати цьому датасету. Калібрування за реальним
модемом і оцінювання sim2real залишаються окремим етапом.
