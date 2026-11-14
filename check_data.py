import glob
import gzip
import json
import math
import os
import random
import sys
import zlib
from collections import defaultdict


ROOT = os.path.dirname(os.path.abspath(__file__))
EXPECTED_CLIMATE_YEARS = set(range(1991, 2027))
EXPECTED_HISTORY_YEARS = set(range(2016, 2027))
CLIMATE_SAMPLE_SIZE = 5
RANDOM_SEED = 42
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

anomalies = defaultdict(list)


def report(category, item):
    anomalies[category].append(item)


def examples(items, limit=8):
    shown = items[:limit]
    suffix = " ..." if len(items) > limit else ""
    return ", ".join(str(item) for item in shown) + suffix


def read_gzip_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return json.load(file)


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# Fields: IDs, chunk keys, areas, and history consistency.
field_files = sorted(glob.glob(os.path.join(ROOT, "fields", "*.json.gz")))
field_record_copies = defaultdict(list)
field_id_occurrences = defaultdict(list)
fields_with_history = set()
fields_without_history = set()
field_names = defaultdict(set)
history_gap_fields = {}
long_crop_runs = {}
invalid_area = set()
invalid_history = set()
field_record_count = 0
history_record_count = 0

for path in field_files:
    filename = os.path.basename(path)
    expected_ck = filename[:-len(".json.gz")]
    try:
        data = read_gzip_json(path)
    except (OSError, EOFError, UnicodeError, zlib.error, json.JSONDecodeError) as error:
        report("invalid_fields_json", f"{filename}: {error}")
        continue

    if not isinstance(data, dict):
        report("invalid_fields_json", f"{filename}: root is not an object")
        continue

    if data.get("ck") != expected_ck:
        report("chunk_key_mismatch", f"{filename}: ck={data.get('ck')!r}")

    records = data.get("fields")
    if not isinstance(records, list):
        report("invalid_fields_json", f"{filename}: fields is not an array")
        continue

    for record in records:
        if not isinstance(record, dict):
            report("invalid_fields_json", f"{filename}: non-object field record")
            continue

        field_id = record.get("id")
        if not isinstance(field_id, str) or not field_id:
            report("missing_field_id", filename)
            continue

        field_id_occurrences[field_id].append(filename)
        field_record_copies[field_id].append(record)
        field_record_count += 1

        if "name" in record and isinstance(record["name"], str) and record["name"].strip():
            field_names[record["name"].strip().casefold()].add(field_id)

        area = record.get("ha")
        if not finite_number(area) or area <= 0:
            invalid_area.add(field_id)

        history = record.get("hist")
        if not isinstance(history, list):
            invalid_history.add(field_id)
            continue

        if not history:
            fields_without_history.add(field_id)
            continue

        history_record_count += 1
        fields_with_history.add(field_id)
        valid_entries = []
        seen_years = set()

        for entry in history:
            if not isinstance(entry, dict):
                invalid_history.add(field_id)
                continue

            year = entry.get("y")
            crop = entry.get("k")
            if not isinstance(year, int) or isinstance(year, bool):
                invalid_history.add(field_id)
                continue

            if year in seen_years:
                report("duplicate_history_years", field_id)
            seen_years.add(year)

            if crop is None:
                invalid_history.add(field_id)
            valid_entries.append((year, crop))

        if seen_years:
            missing = sorted(EXPECTED_HISTORY_YEARS - seen_years)
            if missing:
                history_gap_fields.setdefault(field_id, missing)
            unexpected = sorted(seen_years - EXPECTED_HISTORY_YEARS)
            if unexpected:
                report("unexpected_history_years", f"{field_id}: {unexpected}")

        # A long run is only a review heuristic; broad labels are excluded.
        valid_entries.sort()
        run_crop = None
        run_length = 0
        previous_year = None
        longest_run = (0, None, None, None)
        for year, crop in valid_entries:
            if crop in (None, "other", "uncultivated"):
                run_crop, run_length, previous_year = None, 0, None
                continue
            if crop == run_crop and previous_year is not None and year == previous_year + 1:
                run_length += 1
            else:
                run_crop, run_length = crop, 1
            previous_year = year
            if run_length > longest_run[0]:
                longest_run = (run_length, crop, year - run_length + 1, year)
        if longest_run[0] >= 5:
            previous = long_crop_runs.get(field_id)
            if previous is None or longest_run[0] > previous[0]:
                long_crop_runs[field_id] = longest_run

for field_id, filenames in field_id_occurrences.items():
    if len(filenames) > 1:
        copies = field_record_copies[field_id]
        conflicting = any(record != copies[0] for record in copies[1:])
        report(
            "duplicate_field_ids",
            f"{field_id} ({len(filenames)} records; conflicting={conflicting})",
        )

duplicate_names = [
    (name, ids) for name, ids in field_names.items() if len(ids) > 1
]
for name, ids in duplicate_names:
    report("duplicate_field_names", f"{name!r} ({len(ids)} records)")

for field_id in invalid_area:
    report("invalid_area", field_id)
for field_id in invalid_history:
    report("invalid_history", field_id)
for field_id, years in history_gap_fields.items():
    report("history_year_gaps", f"{field_id}: {years}")
for field_id, (length, crop, start, end) in long_crop_runs.items():
    report("five_year_crop_runs", f"{field_id}: {crop} {start}-{end} ({length} years)")


# Curves: map each curve ID to its source chunk and compare with field IDs.
curve_files = sorted(glob.glob(os.path.join(ROOT, "curves", "*.json.gz")))
curve_id_occurrences = defaultdict(list)
for path in curve_files:
    filename = os.path.basename(path)
    try:
        data = read_gzip_json(path)
    except (OSError, EOFError, UnicodeError, zlib.error, json.JSONDecodeError) as error:
        report("invalid_curves_json", f"{filename}: {error}")
        continue

    if not isinstance(data, dict) or not isinstance(data.get("curves"), dict):
        report("invalid_curves_json", f"{filename}: missing curves object")
        continue

    for field_id in data["curves"]:
        curve_id_occurrences[field_id].append(filename)

for field_id, filenames in curve_id_occurrences.items():
    if len(filenames) > 1:
        report("duplicate_curve_ids", f"{field_id} ({len(filenames)} records)")

field_ids = set(field_id_occurrences)
curve_ids = set(curve_id_occurrences)
fields_without_curves = field_ids - curve_ids
curves_without_fields = curve_ids - field_ids
fields_with_history_without_curves = fields_with_history - curve_ids
curves_without_history = curve_ids - fields_with_history
for field_id in fields_with_history_without_curves:
    report("history_without_curve", field_id)
for field_id in curves_without_fields:
    report("curve_without_field", field_id)


# Climate: inspect year coverage for every file; inspect values in a stable sample.
climate_files = sorted(glob.glob(os.path.join(ROOT, "climate", "*.json")))
climate_data = {}
for path in climate_files:
    filename = os.path.basename(path)
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        report("invalid_climate_json", f"{filename}: {error}")
        continue

    if not isinstance(data, dict) or not isinstance(data.get("years"), list):
        report("invalid_climate_json", f"{filename}: missing years array")
        continue

    climate_data[filename] = data
    years = [
        row.get("y") for row in data["years"]
        if isinstance(row, dict) and isinstance(row.get("y"), int)
    ]
    if len(years) != len(data["years"]):
        report("invalid_climate_years", filename)

    duplicated = sorted({year for year in years if years.count(year) > 1})
    if duplicated:
        report("duplicate_climate_years", f"{filename}: {duplicated}")

    missing_years = sorted(EXPECTED_CLIMATE_YEARS - set(years))
    if missing_years:
        report("climate_year_gaps", f"{filename}: {missing_years}")

sample_names = sorted(climate_data)
random.Random(RANDOM_SEED).shuffle(sample_names)
sample_names = sample_names[:CLIMATE_SAMPLE_SIZE]
temperature_outliers = []
rain_outliers = []

for filename in sample_names:
    for year in climate_data[filename]["years"]:
        if not isinstance(year, dict):
            continue
        values = year.get("tmean", [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, (int, float)) and not finite_number(value):
                report("nonfinite_climate_value", f"{filename}: {year.get('y')}: tmean={value}")
            elif finite_number(value) and (value < -50 or value > 60):
                temperature_outliers.append((filename, year.get("y"), value))

        # The file stores a series of values, not explicitly daily totals.
        values = year.get("rain", [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, (int, float)) and not finite_number(value):
                report("nonfinite_climate_value", f"{filename}: {year.get('y')}: rain={value}")
            elif finite_number(value) and value > 500:
                rain_outliers.append((filename, year.get("y"), value))

for item in temperature_outliers:
    report("climate_temperature_outliers", item)
for item in rain_outliers:
    report("climate_rain_outliers", item)


# Oblast names/codes and polygon coordinate bounds.
oblast_path = os.path.join(ROOT, "oblasts.json")
try:
    with open(oblast_path, "r", encoding="utf-8") as file:
        oblasts = json.load(file)
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    oblasts = {}
    report("invalid_oblasts_json", str(error))

try:
    with open(os.path.join(ROOT, "meta.json"), "r", encoding="utf-8") as file:
        meta = json.load(file)
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    meta = {}
    report("invalid_meta_json", str(error))

meta_oblasts = meta.get("oblasts", {}) if isinstance(meta, dict) else {}
if isinstance(meta_oblasts, dict):
    meta_field_count = sum(
        value.get("fields", 0) for value in meta_oblasts.values()
        if isinstance(value, dict) and isinstance(value.get("fields", 0), int)
    )
    meta_history_count = sum(
        value.get("withHistory", 0) for value in meta_oblasts.values()
        if isinstance(value, dict) and isinstance(value.get("withHistory", 0), int)
    )
    if meta_field_count != field_record_count:
        report("meta_field_count_mismatch", f"meta={meta_field_count}, records={field_record_count}")
    if meta_history_count != history_record_count:
        report("meta_history_count_mismatch", f"meta={meta_history_count}, records={history_record_count}")
else:
    meta_field_count = 0
    meta_history_count = 0

features = oblasts.get("features", []) if isinstance(oblasts, dict) else []
codes = defaultdict(list)
names = defaultdict(list)

# Coarse geographic envelope for Ukraine, including Crimea. This is not a
# political boundary and is only intended to catch grossly misplaced points.
country_bbox = (21.8, 43.9, 40.5, 52.7)


def positions(value):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and finite_number(value[0])
        and finite_number(value[1])
    ):
        yield value[0], value[1]
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from positions(child)


for feature in features:
    if not isinstance(feature, dict):
        report("invalid_oblast_features", "non-object feature")
        continue
    properties = feature.get("properties", {})
    if not isinstance(properties, dict):
        report("invalid_oblast_features", "properties is not an object")
        continue

    code = properties.get("code")
    name = properties.get("name")
    codes[str(code)].append(name)
    names[str(name).strip().casefold()].append(code)

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        report("invalid_oblast_geometry", f"{name}: missing geometry")
        continue

    points = list(positions(geometry.get("coordinates")))
    if not points:
        report("invalid_oblast_geometry", f"{name}: no valid coordinates")
        continue

    min_lon = min(point[0] for point in points)
    min_lat = min(point[1] for point in points)
    max_lon = max(point[0] for point in points)
    max_lat = max(point[1] for point in points)

    if any(
        lon < country_bbox[0] - 0.02 or lon > country_bbox[2] + 0.02
        or lat < country_bbox[1] - 0.02 or lat > country_bbox[3] + 0.02
        for lon, lat in points
    ):
        report("oblast_outside_country_bbox", f"{name}: {(min_lon, min_lat, max_lon, max_lat)}")

for code, values in codes.items():
    if len(values) > 1:
        report("duplicate_oblast_codes", f"{code}: {values}")
for name, values in names.items():
    if len(values) > 1:
        report("duplicate_oblast_names", f"{name}: {values}")


# Summary only; do not dump source records.
print(
    f"Файли: fields={len(field_files)}, curves={len(curve_files)}, "
    f"climate={len(climate_files)}, oblasts={len(features)}"
)
print(
    f"ID: fields={len(field_ids)}, curves={len(curve_ids)}, "
    f"з історією={len(fields_with_history)}, без історії={len(fields_without_history)}"
)
print(
    f"Meta totals: fields={meta_field_count}, records={field_record_count}, "
    f"unique IDs={len(field_ids)}; withHistory={meta_history_count}, "
    f"non-empty history records={history_record_count}"
)
print(
    f"Порівняння ID: без кривої={len(fields_without_curves)}, "
    f"крива без поля={len(curves_without_fields)}, "
    f"історія без кривої={len(fields_with_history_without_curves)}, "
    f"крива без непорожньої історії={len(curves_without_history)}"
)
print(
    f"Назви полів: записів із name={sum(len(ids) for ids in field_names.values())}, "
    f"дубльованих name={len(duplicate_names)}"
)
print(
    f"Кліматична вибірка (seed={RANDOM_SEED}): "
    f"{', '.join(sample_names) if sample_names else '(немає файлів)'}"
)
print(
    "Нульові/позитивні перевірки: "
    f"invalid_area={len(anomalies['invalid_area'])}, "
    f"invalid_history={len(anomalies['invalid_history'])}, "
    f"field_ck_mismatch={len(anomalies['chunk_key_mismatch'])}, "
    f"climate_year_gaps={len(anomalies['climate_year_gaps'])}, "
    f"temperature_outliers={len(anomalies['climate_temperature_outliers'])}, "
    f"rain_outliers={len(anomalies['climate_rain_outliers'])}, "
    f"outside_country_bbox={len(anomalies['oblast_outside_country_bbox'])}"
)

nonempty_anomalies = {
    category: items for category, items in anomalies.items() if items
}
anomaly_count = sum(len(items) for items in nonempty_anomalies.values())
print(f"\nЗнайдено {anomaly_count} аномалій:")
if not nonempty_anomalies:
    print("- Потенційних аномалій не виявлено.")
else:
    for category, items in sorted(nonempty_anomalies.items()):
        print(f"- {category}: {len(items)}; приклади: {examples(items)}")

print(
    "\nПримітки: кліматичні значення перевірені лише у фіксованій вибірці; "
    "порогові значення — tmean поза [-50, 60] та rain > 500 за один запис "
    "(не стверджується, що rain є добовою сумою). Пропуски років в історії "
    "перевіряються за очікуваним діапазоном 2016–2026; пропуск може бути "
    "браком спостережень, а не помилкою даних. "
    "П’ятирічна повторюваність культури — евристичне попередження. "
    "Bbox oblasts — груба прямокутна перевірка, не точна перевірка державного кордону. "
    "Відсутні криві для полів без історії не рахуються аномалією."
)
