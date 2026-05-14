#!/usr/bin/env python3
import csv
import gzip
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SOURCE_CANDIDATES = [
    DATA / "deals_source.csv",
    DATA / "deals_latest.csv",
]

OUT_CSV = DATA / "deals_latest.csv"
OUT_GZ = DATA / "deals_latest.csv.gz"

MIN_ROWS = int(os.environ.get("MIN_DEALS_ROWS", "10"))

REQUIRED_HEADERS = [
    "кадастровый квартал",
    "тип сделки",
    "год",
    "квартал сделки",
    "адрес",
    "ври",
    "площадь",
    "цена",
    "договор",
]

def norm(s):
    return (s or "").strip().lower().replace("_", " ")

def pick_source():
    for p in SOURCE_CANDIDATES:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)

        delimiter = ";"
        if sample.count(",") > sample.count(";"):
            delimiter = ","

        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise SystemExit("ERROR: empty CSV header")

        field_map = {}
        for h in reader.fieldnames:
            nh = norm(h)
            for req in REQUIRED_HEADERS:
                if nh == norm(req):
                    field_map[req] = h

        missing = [h for h in REQUIRED_HEADERS if h not in field_map]
        if missing:
            raise SystemExit("ERROR: missing columns: " + ", ".join(missing))

        rows = []
        seen = set()

        for row in reader:
            out = {}
            for req in REQUIRED_HEADERS:
                out[req] = (row.get(field_map[req]) or "").strip()

            q = out["кадастровый квартал"]
            year = out["год"]
            pq = out["квартал сделки"]

            if not q or q.count(":") < 2:
                continue
            if not year.isdigit():
                continue
            if pq and not pq.isdigit():
                continue

            key = tuple(out[h] for h in REQUIRED_HEADERS)
            if key in seen:
                continue
            seen.add(key)
            rows.append(out)

    return rows

def main():
    source = pick_source()
    if not source:
        raise SystemExit("ERROR: no source file. Put data/deals_source.csv first.")

    rows = read_csv(source)

    if len(rows) < MIN_ROWS:
        raise SystemExit(
            f"ERROR: too few rows: {len(rows)}. "
            f"MIN_DEALS_ROWS={MIN_ROWS}. "
            f"Source: {source}"
        )

    DATA.mkdir(parents=True, exist_ok=True)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_HEADERS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    with OUT_CSV.open("rb") as src, gzip.open(OUT_GZ, "wb", compresslevel=9) as dst:
        dst.write(src.read())

    print("BUILD DEALS RELEASE")
    print("source:", source)
    print("rows:", len(rows))
    print("csv:", OUT_CSV, OUT_CSV.stat().st_size, "bytes")
    print("gz:", OUT_GZ, OUT_GZ.stat().st_size, "bytes")

if __name__ == "__main__":
    main()
