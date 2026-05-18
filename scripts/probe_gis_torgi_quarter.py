#!/usr/bin/env python3
import json
import sys
import zipfile
import urllib.parse
import urllib.request
import traceback
from pathlib import Path
from xml.etree import ElementTree as ET

quarter = sys.argv[1] if len(sys.argv) > 1 else "71:22:050123"

OUT = Path("gis_torgi_probe_out")
OUT.mkdir(parents=True, exist_ok=True)

TIMEOUT = 15
q = urllib.parse.quote(quarter)

urls = {
    "search_plain": f"https://torgi.gov.ru/new/api/public/lotcards/search?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}",
    "search_cat_302": f"https://torgi.gov.ru/new/api/public/lotcards/search?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}&catCode=302",
    "export_plain": f"https://torgi.gov.ru/new/api/public/lotcards/export/excel?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}",
    "export_cat_302": f"https://torgi.gov.ru/new/api/public/lotcards/export/excel?byFirstVersion=true&withFacets=true&sort=firstVersionPublicationDate%2Cdesc&text={q}&catCode=302",
}

headers = {
    "User-Agent": "Mozilla/5.0 ZemelnyGorizontProbe/1.0",
    "Accept": "application/json, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*",
}

print("=== GIS TORGI QUARTER PROBE SAFE ===")
print("quarter:", quarter)
print("timeout per request:", TIMEOUT)
print()

summary = []

def save_text(name, text):
    p = OUT / name
    p.write_text(text, encoding="utf-8", errors="replace")
    return p

def analyze_xlsx(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            print("xlsx files:", names[:10])
            shared = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for t in root.iter():
                    if t.tag.endswith("}t") or t.tag == "t":
                        if t.text:
                            shared.append(t.text)
                txt = "\n".join(shared[:300])
                save_text(path.stem + "_shared_strings.txt", txt)
                print("shared strings count:", len(shared))
                print("shared strings preview:")
                print(txt[:2000])
            return len(shared)
    except Exception as e:
        print("xlsx analyze error:", repr(e))
        return 0

for mode, url in urls.items():
    print()
    print("=== TRY ===")
    print("mode:", mode)
    print("url:", url)

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status = getattr(r, "status", None)
            ctype = r.headers.get("Content-Type", "")
            data = r.read()

        suffix = ".bin"
        if "json" in ctype:
            suffix = ".json"
        elif "spreadsheet" in ctype or data[:2] == b"PK":
            suffix = ".xlsx"
        elif "text" in ctype or "html" in ctype:
            suffix = ".txt"

        out = OUT / f"{mode}{suffix}"
        out.write_bytes(data)

        print("status:", status)
        print("content-type:", ctype)
        print("bytes:", len(data))
        print("saved:", out)

        item = {
            "mode": mode,
            "url": url,
            "status": status,
            "content_type": ctype,
            "bytes": len(data),
            "file": str(out),
            "ok": True,
        }

        if suffix == ".json":
            try:
                obj = json.loads(data.decode("utf-8", errors="replace"))
                pretty = json.dumps(obj, ensure_ascii=False, indent=2)
                save_text(f"{mode}_pretty.json", pretty)
                print("json type:", type(obj).__name__)
                if isinstance(obj, dict):
                    print("json keys:", list(obj.keys())[:30])
                    for k in ["content", "items", "lotCards", "data", "result"]:
                        v = obj.get(k)
                        if isinstance(v, list):
                            print(f"{k} length:", len(v))
                            item[f"{k}_length"] = len(v)
                elif isinstance(obj, list):
                    print("json list length:", len(obj))
                    item["list_length"] = len(obj)
                print("json preview:")
                print(pretty[:3000])
            except Exception as e:
                print("json parse error:", repr(e))

        elif suffix == ".xlsx":
            item["shared_strings"] = analyze_xlsx(out)

        else:
            preview = data[:3000].decode("utf-8", errors="replace")
            save_text(f"{mode}_preview.txt", preview)
            print("text preview:")
            print(preview)

        summary.append(item)

    except Exception as e:
        print("ERROR:", repr(e))
        traceback.print_exc()
        summary.append({
            "mode": mode,
            "url": url,
            "ok": False,
            "error": repr(e),
        })

summary_path = OUT / "summary.json"
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

print()
print("=== SUMMARY ===")
print(summary_path.read_text(encoding="utf-8"))
print()
print("DONE")
