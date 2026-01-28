#!/usr/bin/env python3
import io
import json
import gzip
import time
import yaml
import hashlib
import warnings
from datetime import datetime, timezone
from collections import OrderedDict
from pathlib import Path

import requests

API_URL = "https://www.dell.com/support/driver/{country}/ips/api/driverlist/fetchdriversbyproduct"
DEFAULT_OSCODES = ["NAA", "W2022", "W2019", "WS16", "WS12R2"]
COUNTRY = "en-us"

OUT_PATH = Path("docs/cpld_latest.json")
MODELS_PATH = Path("models.yaml")

HEADERS = {
    "Accept": "application/json",
    "x-requested-with": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (GitHubActions; +https://github.com/) PythonRequests",
}

def call_dell_api(productcode: str, oscode: str, country: str = COUNTRY, retries: int = 3, backoff: float = 2.0):
    params = {
        "productcode": productcode,
        "oscode": oscode,
        "lob": "PowerEdge",          # <— important for servers
        "initialload": True,
        "_": int(time.time() * 1000),
    }
    url = API_URL.format(country=country)

    headers = dict(HEADERS)
    headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    headers["Referer"] = f"https://www.dell.com/support/home/{country}/product-support/product/{productcode}/drivers"

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            print(f"[debug] GET {resp.url} -> {resp.status_code} {resp.reason}")
            ctype = resp.headers.get("Content-Type","")
            if resp.status_code == 200 and ctype.startswith("application/json"):
                return resp.json()
            elif resp.status_code == 204:
                print("[warn] 204 No Content; retrying...")
                time.sleep(backoff * attempt)
            else:
                print(f"[warn] Unexpected status {resp.status_code} (Content-Type={ctype}); retrying...")
                time.sleep(backoff * attempt)
        except Exception as e:
            last_exc = e
            print(f"[error] Exception: {e}; retrying...")
            time.sleep(backoff * attempt)
    if last_exc:
        warnings.warn(f"call_dell_api({productcode}, {oscode}) failed: {last_exc}")
    return None

def parse_rows(driver_json: dict):
    rows = []
    if not driver_json or "DriverListData" not in driver_json:
        return rows
    for d in driver_json["DriverListData"]:
        rd_raw = d.get("ReleaseDate")
        lu_raw = d.get("LUPDDate")
        def parse_date(s):
            try:
                return datetime.strptime(s, "%d %b %Y").date()
            except Exception:
                return None
        rows.append(OrderedDict([
            ("ReleaseDate", parse_date(rd_raw)),
            ("ReleaseDateRaw", rd_raw),
            ("LastUpdate", parse_date(lu_raw)),
            ("UpdateStatus", d.get("Imp")),
            ("Version", d.get("DellVer")),
            ("Name", d.get("DriverName", "")),
            ("Category", d.get("Category", "")),
            ("DriverId", d.get("DriverId") or d.get("DriverIdEN") or (d.get("FileFrmtInfo") or {}).get("FileId")),
            ("DownloadUrl", (d.get("FileFrmtInfo") or {}).get("Path")),
        ]))
    return rows

def is_cpld(row: dict) -> bool:
    name = (row.get("Name") or "").lower()
    cat  = (row.get("Category") or "").lower()
    return ("cpld" in name) or ("cpld" in cat) or ("complex programmable logic" in name)

def find_latest_cpld(productcode: str, oscodes=None, country=COUNTRY):
    oscodes = oscodes or DEFAULT_OSCODES
    best = None
    for oscode in oscodes:
        data = call_dell_api(productcode, oscode, country=country)
        rows = parse_rows(data)
        cpld_rows = [r for r in rows if is_cpld(r)]
        if not cpld_rows:
            continue
        cpld_rows.sort(key=lambda r: (r.get("ReleaseDate") or datetime.min.date()), reverse=True)
        candidate = cpld_rows[0]
        if best is None or (candidate.get("ReleaseDate") or datetime.min.date()) > (best.get("ReleaseDate") or datetime.min.date()):
            best = candidate
    return best

def load_models(yaml_path=MODELS_PATH):
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return data.get("servers", [])

def write_if_changed(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if hashlib.sha256(old.encode()).hexdigest() != hashlib.sha256(content.encode()).hexdigest():
        path.write_text(content, encoding="utf-8")
        return True
    return False

def main():
    servers = load_models()
    result = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": "dell fetchdriversbyproduct",
        "country": COUNTRY,
        "data": {}
    }

    for s in servers:
        productcode = s["productcode"]
        oscodes = s.get("oscodes", None)
        latest = find_latest_cpld(productcode, oscodes=oscodes)
        if latest:
            result["data"][productcode] = {
                "name": latest.get("Name"),
                "version": latest.get("Version"),
                "release_date": (latest.get("ReleaseDate") or ""),
                "driver_id": latest.get("DriverId"),
                "download_url": latest.get("DownloadUrl"),
                "category": latest.get("Category"),
            }
        else:
            result["data"][productcode] = None

    json_str = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    changed = write_if_changed(OUT_PATH, json_str)
    print(f"Wrote {OUT_PATH} (changed={changed})")

if __name__ == "__main__":
    main()
