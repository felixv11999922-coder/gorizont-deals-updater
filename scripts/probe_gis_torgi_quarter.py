#!/usr/bin/env python3
import csv
import json
import sys
import zipfile
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

quarter = sys.argv[1] if len(sys.argv) > 1 else "71:22:050123"

OUT = Path("gis_torgi_probe_out")
OUT.mkdir(parents=True, exist_ok=True)

q = urllib.parse.quote(quarter)

URLS = {
    "search_plain": f"https://torgi.gov.ru/new/api/public/lotcards/search?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}",
    "search_cat_302": f"https://torgi.gov.ru/new/api/public/lotcards/search?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}&catCode=302",
    "export_plain": f"https://torgi.gov.ru/new/api/public/lotcards/export/excel?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}",
    "export_cat_302": f"https://torgi.gov.ru/new/api/public/lotcards/export/excel?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}&catCode=302",
}

def save_text(name, text):
    p = OUT / name
    p.write_text(text, encoding="utf-8", errors="replace")
    return p

def extract_xlsx_text(path):
    rows = []

    with zipfile.ZipFile(path) as z:
        shared = []

        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("a:si", ns):
                parts = []
                for t in si.findall(".//a:t", ns):
                    parts.append(t.text or "")
                shared.append("".join(parts))

        sheet_names = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]

        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

        for sheet in sheet_names:
            root = ET.fromstring(z.read(sheet))
            for row in root.findall(".//a:row", ns):
                values = []
                for c in row.findall("a:c", ns):
                    v = c.find("a:v", ns)
                    if v is None:
                        values.append("")
                        continue

                    raw = v.text or ""
                    if c.attrib.get("t") == "s":
                        try:
                            values.append(shared[int(raw)])
                        except Exception:
                            values.append(raw)
                    else:
                        values.append(raw)

                if any(values):
                    rows.append(values)

    return rows

print("=== GIS TORGI GITHUB ACTION PROBE ===")
print("quarter:", quarter)
print()

summary = []

for mode, url in URLS.items():
    print("=== TRY ===")
    print("mode:", mode)
    print("url:", url)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ZemelnyGorizontPRO/1.0",
            "Accept": "*/*",
            "Accept-Language": "ru,en;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            status = getattr(r, "status", None)
            ctype = r.headers.get("content-type", "")
            data = r.read()

        print("status:", status)
        print("content-type:", ctype)
        print("bytes:", len(data))

        raw_path = OUT / f"{mode}.bin"
        raw_path.write_bytes(data)

        if data[:2] == b"PK":
            xlsx_path = OUT / f"{mode}.xlsx"
            xlsx_path.write_bytes(data)

            rows = extract_xlsx_text(xlsx_path)
            csv_path = OUT / f"{mode}_extracted.csv"

            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerows(rows)

            matches = [row for row in rows if quarter in " ".join(row)]

            print("xlsx rows:", len(rows))
            print("xlsx quarter matches:", len(matches))

            match_path = OUT / f"{mode}_matches.csv"
            with match_path.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerows(matches[:200])

            for row in matches[:10]:
                print("MATCH:", " | ".join(row[:12]))

            summary.append([mode, status, ctype, len(data), len(rows), len(matches), "xlsx"])

        else:
            text = data.decode("utf-8", errors="replace")
            save_text(f"{mode}.txt", text[:500000])

            try:
                obj = json.loads(text)
                save_text(f"{mode}.json", json.dumps(obj, ensure_ascii=False, indent=2)[:1000000])

                if isinstance(obj, dict):
                    total = obj.get("totalElements") or obj.get("total") or obj.get("count")
                    content = obj.get("content") or obj.get("data") or obj.get("items") or []
                    print("json total:", total)
                    print("json content/items:", len(content) if isinstance(content, list) else type(content).__name__)
                else:
                    print("json type:", type(obj).__name__)

                found = quarter in text
                print("text contains quarter:", found)
                summary.append([mode, status, ctype, len(data), "", 1 if found else 0, "json/text"])

            except Exception as e:
                print("not json:", repr(e))
                found = quarter in text
                print("text contains quarter:", found)
                summary.append([mode, status, ctype, len(data), "", 1 if found else 0, "text"])

    except Exception as e:
        print("ERROR:", repr(e))
        save_text(f"{mode}_error.txt", repr(e))
        summary.append([mode, "ERROR", "", "", "", "", repr(e)])

    print()

summary_path = OUT / "summary.csv"
with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["mode", "status", "content_type", "bytes", "rows", "matches", "kind"])
    w.writerows(summary)

print("=== SUMMARY ===")
for row in summary:
    print(row)

print()
print("saved to:", OUT)
