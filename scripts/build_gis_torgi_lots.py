#!/usr/bin/env python3
import csv
import gzip
import hashlib
import os
import re
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

OUT = Path("data")
OUT.mkdir(parents=True, exist_ok=True)

CSV_GZ = OUT / "gis_torgi_lots_latest.csv.gz"

CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}(?::\d+)?\b")
LOT_RE = re.compile(r"\b\d{10,}_\d+\b")

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


def norm(value):
    return str(value or "").strip()


def low(value):
    return norm(value).lower()


def pick(row, *needles):
    for key, value in row.items():
        k = low(key)
        if all(n in k for n in needles):
            v = norm(value)
            if v and v.lower() != "nan":
                return v
    return ""


def first_non_empty(row):
    for value in row.values():
        v = norm(value)
        if v and v.lower() != "nan" and len(v) > 10:
            return v
    return ""


def extract_record(source_label, row):
    full = " | ".join(norm(v) for v in row.values())

    source_url = ""
    for value in row.values():
        v = norm(value)
        if "torgi.gov.ru" in v:
            source_url = v
            break

    lot_id = (
        pick(row, "номер", "лота")
        or pick(row, "лот")
        or pick(row, "извещ")
        or pick(row, "id")
    )

    if not lot_id:
        m = LOT_RE.search(source_url or full)
        if m:
            lot_id = m.group(0)

    if not lot_id:
        lot_id = source_label + "_" + hashlib.sha256(full.encode("utf-8")).hexdigest()[:20]

    cad = ""
    m = CAD_RE.search(full)
    if m:
        cad = m.group(0)

    title = (
        pick(row, "предмет")
        or pick(row, "наименование", "лота")
        or pick(row, "наименование")
        or first_non_empty(row)
    )

    description = pick(row, "описание") or pick(row, "сведения") or pick(row, "характерист")
    region = pick(row, "субъект") or pick(row, "регион")
    address = pick(row, "адрес") or pick(row, "местоположение")
    price = pick(row, "начальная", "цена") or pick(row, "цена") or pick(row, "плата")
    area = pick(row, "площад")
    status = pick(row, "статус") or pick(row, "состояние")

    published_at = pick(row, "публикац") or pick(row, "размещ")
    bid_end_at = pick(row, "оконч", "заяв") or pick(row, "прием", "заяв")
    auction_at = pick(row, "дата", "торг") or pick(row, "аукцион")

    return {
        "lot_id": lot_id[:200],
        "source_label": source_label,
        "source_url": source_url[:1000],
        "title": title[:1000],
        "description": description[:2000],
        "region": region[:500],
        "address": address[:1000],
        "cadastral_number": cad[:100],
        "area_text": area[:300],
        "price_text": price[:300],
        "status": status[:300],
        "published_at": published_at[:100],
        "bid_end_at": bid_end_at[:100],
        "auction_at": auction_at[:100],
    }


def load_url(label, url):
    print(f"FETCH {label}: {url}")
    r = requests.get(
        url,
        timeout=90,
        headers={
            "User-Agent": "ZemelnyGorizontPRO GitHub Actions collector",
            "Accept": "*/*",
        },
    )
    r.raise_for_status()

    print(f"  bytes={len(r.content)} content_type={r.headers.get('content-type')}")

    df = pd.read_excel(BytesIO(r.content), dtype=str)
    df = df.fillna("")
    print(f"  rows={len(df)} cols={len(df.columns)}")

    records = []
    for raw in df.to_dict(orient="records"):
        text = " ".join(norm(v).lower() for v in raw.values())
        if not any(x in text for x in ["земель", "участ", "кадастр", "аренд", "собствен"]):
            continue
        records.append(extract_record(label, raw))

    print(f"  relevant={len(records)}")
    return records


def main():
    all_records = {}
    errors = []

    for label, url in URLS:
        try:
            for rec in load_url(label, url):
                all_records[rec["lot_id"]] = rec
        except Exception as e:
            print(f"ERROR {label}: {e!r}")
            errors.append((label, repr(e)))

    records = list(all_records.values())
    min_rows = int(os.environ.get("MIN_GIS_TORGI_ROWS", "1"))

    print()
    print("SUMMARY")
    print("records:", len(records))
    print("errors:", errors)

    if len(records) < min_rows:
        raise SystemExit(f"too few rows: {len(records)} < {min_rows}")

    with gzip.open(CSV_GZ, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)

    print("written:", CSV_GZ)
    print("size:", CSV_GZ.stat().st_size)


if __name__ == "__main__":
    main()
