#!/usr/bin/env python3
import csv
import gzip
import hashlib
import os
import re
import sys
from pathlib import Path

import pandas as pd


BASE = Path(".")
INPUT_DIR = BASE / "data" / "manual_gis_torgi"
OUT_DIR = BASE / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CSV_GZ = OUT_DIR / "gis_torgi_lots_latest.csv.gz"

CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}(?::\d+)?\b")
LOT_RE = re.compile(r"\b\d{10,}_\d+\b")

FIELDS = [
    "lot_id",
    "source_label",
    "source_url",
    "title",
    "description",
    "region",
    "address",
    "cadastral_number",
    "area_text",
    "price_text",
    "status",
    "published_at",
    "bid_end_at",
    "auction_at",
]


def log(message: str) -> None:
    print(message, flush=True)


def norm(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def low(value) -> str:
    return norm(value).lower()


def pick(row: dict, *needles: str) -> str:
    for key, value in row.items():
        key_text = low(key)
        if all(needle in key_text for needle in needles):
            result = norm(value)
            if result:
                return result
    return ""


def first_non_empty(row: dict) -> str:
    for value in row.values():
        result = norm(value)
        if result and len(result) > 10:
            return result
    return ""


def is_relevant_land_row(row: dict) -> bool:
    text = " ".join(norm(v).lower() for v in row.values())
    return any(
        marker in text
        for marker in [
            "земель",
            "участ",
            "кадастр",
            "аренд",
            "собствен",
            "земли",
            "лот",
            "торг",
        ]
    )


def extract_record(source_label: str, row: dict) -> dict:
    full = " | ".join(norm(v) for v in row.values())

    source_url = ""
    for value in row.values():
        text = norm(value)
        if "torgi.gov.ru" in text:
            source_url = text
            break

    lot_id = (
        pick(row, "номер", "лота")
        or pick(row, "номер", "процед")
        or pick(row, "извещ")
        or pick(row, "лот")
        or pick(row, "id")
    )

    if not lot_id:
        match = LOT_RE.search(source_url or full)
        if match:
            lot_id = match.group(0)

    if not lot_id:
        lot_id = source_label + "_" + hashlib.sha256(full.encode("utf-8")).hexdigest()[:20]

    cadastral_number = ""
    cad_match = CAD_RE.search(full)
    if cad_match:
        cadastral_number = cad_match.group(0)

    title = (
        pick(row, "предмет")
        or pick(row, "наименование", "лота")
        or pick(row, "наименование")
        or pick(row, "объект")
        or first_non_empty(row)
    )

    description = (
        pick(row, "описание")
        or pick(row, "сведения")
        or pick(row, "характерист")
        or pick(row, "информация")
    )

    region = (
        pick(row, "субъект")
        or pick(row, "регион")
        or pick(row, "местонахождение")
        or pick(row, "место", "нахождения")
    )

    address = (
        pick(row, "адрес")
        or pick(row, "местоположение")
        or pick(row, "место", "нахождения")
    )

    price = (
        pick(row, "начальная", "цена")
        or pick(row, "цена")
        or pick(row, "размер", "платы")
        or pick(row, "арендная", "плата")
    )

    area = pick(row, "площад")

    status = (
        pick(row, "статус")
        or pick(row, "состояние")
    )

    published_at = (
        pick(row, "дата", "публикац")
        or pick(row, "публикац")
        or pick(row, "размещ")
    )

    bid_end_at = (
        pick(row, "оконч", "заяв")
        or pick(row, "прием", "заяв")
        or pick(row, "подач", "заяв")
    )

    auction_at = (
        pick(row, "дата", "торг")
        or pick(row, "провед", "аукцион")
        or pick(row, "аукцион")
    )

    return {
        "lot_id": lot_id[:200],
        "source_label": source_label[:200],
        "source_url": source_url[:1000],
        "title": title[:1000],
        "description": description[:2000],
        "region": region[:500],
        "address": address[:1000],
        "cadastral_number": cadastral_number[:100],
        "area_text": area[:300],
        "price_text": price[:300],
        "status": status[:300],
        "published_at": published_at[:100],
        "bid_end_at": bid_end_at[:100],
        "auction_at": auction_at[:100],
    }


def read_csv_file(path: Path) -> list[dict]:
    log(f"READ CSV: {path}")

    if str(path).endswith(".gz"):
        opener = lambda: gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    else:
        opener = lambda: open(path, "r", encoding="utf-8", errors="replace", newline="")

    with opener() as file:
        sample = file.read(4096)
        file.seek(0)

        delimiter = ";"
        if sample.count(",") > sample.count(";"):
            delimiter = ","

        reader = csv.DictReader(file, delimiter=delimiter)
        rows = [dict(row) for row in reader]

    log(f"  rows={len(rows)}")
    return rows


def read_xlsx_file(path: Path) -> list[dict]:
    log(f"READ XLSX: {path}")

    all_rows: list[dict] = []

    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    for sheet_name, df in sheets.items():
        df = df.fillna("")
        log(f"  sheet={sheet_name!r} rows={len(df)} cols={len(df.columns)}")
        for row in df.to_dict(orient="records"):
            row["_sheet"] = sheet_name
            all_rows.append(row)

    log(f"  total_rows={len(all_rows)}")
    return all_rows


def read_input_file(path: Path) -> list[dict]:
    suffixes = "".join(path.suffixes).lower()

    if suffixes.endswith(".xlsx"):
        return read_xlsx_file(path)

    if suffixes.endswith(".csv") or suffixes.endswith(".csv.gz"):
        return read_csv_file(path)

    log(f"SKIP unsupported file: {path}")
    return []


def find_input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []

    files = []
    for path in sorted(INPUT_DIR.rglob("*")):
        if not path.is_file():
            continue

        name = path.name.lower()
        if name.endswith(".xlsx") or name.endswith(".csv") or name.endswith(".csv.gz"):
            files.append(path)

    return files


def write_csv_gz(records: list[dict]) -> None:
    with gzip.open(CSV_GZ, "wt", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)

    log(f"written: {CSV_GZ}")
    log(f"size: {CSV_GZ.stat().st_size}")


def main() -> None:
    log("GIS TORGI LOTS BUILDER — MANUAL FILE MODE")
    log(f"python: {sys.version}")
    log(f"input_dir: {INPUT_DIR}")
    log(f"output: {CSV_GZ}")

    input_files = find_input_files()

    if not input_files:
        log("")
        log("ERROR: no input files found")
        log("Put .xlsx, .csv or .csv.gz files into data/manual_gis_torgi/")
        raise SystemExit(2)

    log("")
    log("INPUT FILES:")
    for path in input_files:
        log(f"- {path}")

    all_records: dict[str, dict] = {}

    for path in input_files:
        source_label = path.stem[:120]
        rows = read_input_file(path)

        relevant = 0
        for row in rows:
            if not is_relevant_land_row(row):
                continue

            record = extract_record(source_label, row)
            all_records[record["lot_id"]] = record
            relevant += 1

        log(f"  relevant={relevant}")

    records = list(all_records.values())
    min_rows = int(os.environ.get("MIN_GIS_TORGI_ROWS", "1"))

    log("")
    log("SUMMARY")
    log(f"records: {len(records)}")
    log(f"min_rows: {min_rows}")

    if len(records) < min_rows:
        raise SystemExit(f"too few rows: {len(records)} < {min_rows}")

    write_csv_gz(records)
    log("DONE")


if __name__ == "__main__":
    main()
