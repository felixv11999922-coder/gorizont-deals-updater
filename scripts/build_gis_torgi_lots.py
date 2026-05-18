#!/usr/bin/env python3
import csv
import gzip
import hashlib
import os
import re
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


OUT = Path("data")
OUT.mkdir(parents=True, exist_ok=True)

CSV_GZ = OUT / "gis_torgi_lots_latest.csv.gz"

CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}(?::\d+)?\b")
LOT_RE = re.compile(r"\b\d{10,}_\d+\b")

REQUEST_TIMEOUT = (10, 25)

URLS = [
    (
        "text_land_plot",
        "https://torgi.gov.ru/new/api/public/lotcards/export/excel"
        "?byFirstVersion=true&filterFavorites=false"
        "&lotStatus=PUBLISHED%2CAPPLICATIONS_SUBMISSION"
        "&sort=firstVersionPublicationDate%2Cdesc"
        "&text=%D0%B7%D0%B5%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9%20%D1%83%D1%87%D0%B0%D1%81%D1%82%D0%BE%D0%BA",
    ),
    (
        "cat_301",
        "https://torgi.gov.ru/new/api/public/lotcards/export/excel"
        "?byFirstVersion=true&catCode=301&filterFavorites=false"
        "&lotStatus=PUBLISHED%2CAPPLICATIONS_SUBMISSION"
        "&sort=firstVersionPublicationDate%2Cdesc",
    ),
    (
        "cat_302",
        "https://torgi.gov.ru/new/api/public/lotcards/export/excel"
        "?byFirstVersion=true&catCode=302&filterFavorites=false"
        "&lotStatus=PUBLISHED%2CAPPLICATIONS_SUBMISSION"
        "&sort=firstVersionPublicationDate%2Cdesc",
    ),
]

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
    status = pick(row, "статус") or pick(row, "состояние")

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
        "source_label": source_label,
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
        ]
    )


def load_url(label: str, url: str) -> list[dict]:
    log("")
    log(f"FETCH {label}: {url}")

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "ZemelnyGorizontPRO GitHub Actions collector",
            "Accept": "*/*",
        },
    )

    log(f"  status={response.status_code}")
    log(f"  bytes={len(response.content)} content_type={response.headers.get('content-type')}")

    response.raise_for_status()

    if not response.content:
        raise RuntimeError("empty response")

    if response.content[:2] != b"PK":
        preview = response.content[:300].decode("utf-8", errors="replace")
        raise RuntimeError(f"response is not XLSX/ZIP, preview={preview!r}")

    df = pd.read_excel(BytesIO(response.content), dtype=str)
    df = df.fillna("")

    log(f"  rows={len(df)} cols={len(df.columns)}")
    log(f"  columns={list(df.columns)[:20]}")

    records = []
    for raw in df.to_dict(orient="records"):
        if not is_relevant_land_row(raw):
            continue
        records.append(extract_record(label, raw))

    log(f"  relevant={len(records)}")
    return records


def write_csv_gz(records: list[dict]) -> None:
    with gzip.open(CSV_GZ, "wt", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)

    log(f"written: {CSV_GZ}")
    log(f"size: {CSV_GZ.stat().st_size}")


def main() -> None:
    log("GIS TORGI LOTS BUILDER")
    log(f"python: {sys.version}")
    log(f"output: {CSV_GZ}")
    log(f"request_timeout: {REQUEST_TIMEOUT}")

    all_records: dict[str, dict] = {}
    errors: list[tuple[str, str]] = []

    for label, url in URLS:
        try:
            records = load_url(label, url)
            for record in records:
                all_records[record["lot_id"]] = record
        except Exception as exc:
            log(f"ERROR {label}: {exc!r}")
            errors.append((label, repr(exc)))

    records = list(all_records.values())
    min_rows = int(os.environ.get("MIN_GIS_TORGI_ROWS", "1"))

    log("")
    log("SUMMARY")
    log(f"records: {len(records)}")
    log(f"errors: {errors}")

    if len(records) < min_rows:
        raise SystemExit(f"too few rows: {len(records)} < {min_rows}")

    write_csv_gz(records)


if __name__ == "__main__":
    main()
