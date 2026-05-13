#!/usr/bin/env python3
"""
Build cadastral_quarters_all.csv for Zemelny Gorizont PRO.

This script collects cadastral quarter codes from one or more CSV sources,
normalizes them, removes duplicates, and writes a clean semicolon-separated CSV.

Output format:
cadastral_quarter;region_code;district_code;quarter_code;source;updated_at

Safe default:
- does not fetch anything from Rosreestr/NSPD by itself;
- only processes local CSV files inside the repository;
- can be used later by GitHub Actions or locally.
"""

import argparse
import csv
import gzip
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_INPUTS = [
    "data/cadastral_quarters_source.csv",
    "data/quarters_seed.csv",
    "data/deals_latest.csv",
]

DEFAULT_OUTPUT = "data/cadastral_quarters_all.csv"


QUARTER_COLUMN_CANDIDATES = [
    "cadastral_quarter",
    "кадастровый_квартал",
    "кадастровый квартал",
    "quarter",
    "kvartal",
    "cad_quarter",
    "code",
]


def open_text(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def detect_delimiter(sample: str) -> str:
    semicolon_count = sample.count(";")
    comma_count = sample.count(",")
    tab_count = sample.count("\t")

    if semicolon_count >= comma_count and semicolon_count >= tab_count:
        return ";"
    if tab_count >= comma_count:
        return "\t"
    return ","


def find_quarter_column(fieldnames):
    if not fieldnames:
        return None

    lower_map = {name.lower().strip(): name for name in fieldnames}

    for candidate in QUARTER_COLUMN_CANDIDATES:
        if candidate in lower_map:
            return lower_map[candidate]

    return fieldnames[0]


def parse_quarter(value: str):
    value = (value or "").strip()

    if not value:
        return None

    value = value.replace(" ", "")

    parts = value.split(":")

    if len(parts) < 3:
        return None

    region_code = parts[0].strip()
    district_code = parts[1].strip()
    quarter_code = ":".join(parts[2:]).strip()

    if not region_code or not district_code or not quarter_code:
        return None

    if not region_code.isdigit():
        return None

    normalized = f"{region_code}:{district_code}:{quarter_code}"

    return {
        "cadastral_quarter": normalized,
        "region_code": region_code,
        "district_code": district_code,
        "quarter_code": quarter_code,
    }


def read_quarters_from_csv(path: Path):
    found = {}
    total_rows = 0
    skipped_rows = 0

    with open_text(path) as f:
        sample = f.read(4096)
        f.seek(0)

        delimiter = detect_delimiter(sample)
        reader = csv.DictReader(f, delimiter=delimiter)

        quarter_col = find_quarter_column(reader.fieldnames)

        if not quarter_col:
            raise RuntimeError(f"Cannot find cadastral quarter column in {path}")

        print(f"Source: {path}")
        print(f"Columns: {reader.fieldnames}")
        print(f"Quarter column: {quarter_col}")
        print(f"Delimiter: {repr(delimiter)}")

        for row in reader:
            total_rows += 1

            parsed = parse_quarter(row.get(quarter_col, ""))

            if not parsed:
                skipped_rows += 1
                continue

            key = parsed["cadastral_quarter"]

            if key not in found:
                found[key] = {
                    **parsed,
                    "source": str(path),
                }

    print(f"Rows read: {total_rows}")
    print(f"Quarters found: {len(found)}")
    print(f"Rows skipped: {skipped_rows}")
    print()

    return found


def write_output(output_path: Path, quarters: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    rows = []

    for quarter in quarters.values():
        rows.append({
            "cadastral_quarter": quarter["cadastral_quarter"],
            "region_code": quarter["region_code"],
            "district_code": quarter["district_code"],
            "quarter_code": quarter["quarter_code"],
            "source": quarter.get("source", ""),
            "updated_at": updated_at,
        })

    rows.sort(key=lambda item: item["cadastral_quarter"])

    fieldnames = [
        "cadastral_quarter",
        "region_code",
        "district_code",
        "quarter_code",
        "source",
        "updated_at",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Output written: {output_path}")
    print(f"Output rows: {len(rows)}")


def main():
    parser = argparse.ArgumentParser(
        description="Build cadastral_quarters_all.csv from local CSV sources."
    )

    parser.add_argument(
        "--input",
        "-i",
        action="append",
        default=[],
        help="Input CSV or CSV.GZ file. Can be used multiple times.",
    )

    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output CSV file. Default: {DEFAULT_OUTPUT}",
    )

    parser.add_argument(
        "--min-rows",
        type=int,
        default=1,
        help="Minimum required number of unique quarters. Default: 1.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate sources but do not write output.",
    )

    args = parser.parse_args()

    input_paths = [Path(p) for p in args.input]

    if not input_paths:
        input_paths = [Path(p) for p in DEFAULT_INPUTS if Path(p).exists()]

    if not input_paths:
        print("ERROR: no input files found.")
        print("Create one of these files first:")
        for item in DEFAULT_INPUTS:
            print(f"  - {item}")
        print()
        print("Or run:")
        print("  python scripts/build_cadastral_quarters.py --input path/to/source.csv")
        sys.exit(1)

    all_quarters = {}

    for path in input_paths:
        if not path.exists():
            print(f"WARNING: input file not found, skipped: {path}")
            continue

        quarters = read_quarters_from_csv(path)
        all_quarters.update(quarters)

    total = len(all_quarters)

    print("Final unique cadastral quarters:", total)
    print("Minimum required:", args.min_rows)

    if total < args.min_rows:
        print("ERROR: too few cadastral quarters.")
        sys.exit(1)

    if args.dry_run:
        print("Dry run mode: output file was not written.")
        return

    write_output(Path(args.output), all_quarters)


if __name__ == "__main__":
    main()
