import argparse
import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

from scrape_reginavi_details import TARGET_FIELDS, best_match, clean_text, normalize_emergency


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
BASE_URL = "https://renewal.e-resident.jp"
LIST_URL = f"{BASE_URL}/hospital/juniorlist"
USER_AGENT = "Mozilla/5.0 (compatible; ITHF-hospital-search/1.0; +https://github.com/halcyon7766/ITHF)"


warnings.filterwarnings("ignore", message="Unverified HTTPS request")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def prefecture_from_address(address):
    match = re.match(r"(.+?[都道府県])", address)
    if not match:
        return ""
    prefecture = match.group(1)
    return prefecture.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県")


def normalize_beds(value):
    value = clean_text(value)
    if not value:
        return ""
    match = re.search(r"([0-9０-９,，]{2,4})", value)
    if not match:
        return ""
    number = match.group(1).translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
    return f"{number}床"


def normalize_quota(value):
    value = clean_text(value)
    if not value:
        return ""
    match = re.search(r"([0-9０-９]{1,3})", value)
    if not match:
        return ""
    number = match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return f"{number}名"


def make_session(timeout):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.request_timeout = timeout
    return session


def get(session, url):
    response = session.get(url, timeout=session.request_timeout, verify=False)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text, response.url


def labeled_values(container):
    values = {}
    for row in container.select("tr"):
        label = row.find("th")
        value = row.find("td")
        if label and value:
            values[clean_text(label.get_text(" ", strip=True))] = clean_text(value.get_text(" ", strip=True))
    return values


def parse_list_page(html, source_url):
    soup = BeautifulSoup(html, "lxml")
    records = []
    for article in soup.select("article.hospital-excerpt"):
        name_node = article.select_one("hgroup.heading h1")
        link_node = article.select_one('hgroup.heading a[href*="/hospital/"][href$="/junior"]')
        if not name_node or not link_node:
            continue

        source = urljoin(BASE_URL, link_node.get("href"))
        values = labeled_values(article)
        address_node = article.select_one(".address")
        address = clean_text(address_node.get_text(" ", strip=True)) if address_node else ""
        records.append(
            {
                "prefecture": prefecture_from_address(address),
                "name": clean_text(name_node.get_text(" ", strip=True)),
                "sourceUrl": source,
                "quota": normalize_quota(values.get("募集定員", "")),
                "beds": normalize_beds(values.get("病床数", "")),
                "salary": "",
                "emergencyCategory": normalize_emergency(values.get("救急指定", "")),
            }
        )
    return records


def fetch_list_page(page, timeout):
    session = make_session(timeout)
    url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
    html, final_url = get(session, url)
    return parse_list_page(html, final_url)


def fetch_list_records(timeout, workers, pages):
    records = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_list_page, page, timeout): page for page in range(1, pages + 1)}
        for future in as_completed(futures):
            page = futures[future]
            try:
                page_records = future.result()
            except Exception as exc:
                print(f"page {page}: failed: {exc}")
                continue
            print(f"page {page}: {len(page_records)} records")
            records.extend(page_records)
    return records


def parse_definition_list(html):
    soup = BeautifulSoup(html, "lxml")
    values = {}
    for dl in soup.select("dl"):
        current = None
        for child in dl.find_all(["dt", "dd"], recursive=False):
            text = clean_text(child.get_text(" ", strip=True))
            if not text:
                continue
            if child.name == "dt":
                current = text
                values.setdefault(current, [])
            elif current:
                values.setdefault(current, []).append(text)
    return values


def first_value(values, labels):
    for label in labels:
        for key, entries in values.items():
            if label in key and entries:
                return clean_text(entries[0])
    return ""


def parse_youkou_page(html, source_url):
    values = parse_definition_list(html)
    salary = first_value(values, ["給与１年次", "給与1年次", "給与"])
    return {
        "quota": normalize_quota(first_value(values, ["募集定員"])),
        "beds": "",
        "salary": f"給与1年次 {salary}" if salary else "",
        "emergencyCategory": "",
        "sourceUrl": source_url,
    }


def fetch_youkou(record, timeout):
    session = make_session(timeout)
    url = f"{record['sourceUrl'].rstrip('/')}/youkou"
    html, final_url = get(session, url)
    details = parse_youkou_page(html, final_url)
    return record["sourceUrl"], details


def index_hospitals(data):
    by_prefecture = {}
    for hospital in data["hospitals"]:
        by_prefecture.setdefault(hospital["prefecture"], []).append(hospital)
    return by_prefecture


def apply_list_records(data, records, overwrite=False):
    by_prefecture = index_hospitals(data)
    stats = {
        "records": len(records),
        "matched": 0,
        "ambiguousOrUnmatched": 0,
        "updatedHospitals": 0,
        "filled": {field: 0 for field in TARGET_FIELDS},
    }
    matched_records = []

    for record in records:
        candidates = by_prefecture.get(record["prefecture"], data["hospitals"])
        hospital, score = best_match(record, candidates)
        if not hospital:
            stats["ambiguousOrUnmatched"] += 1
            continue

        stats["matched"] += 1
        matched_records.append((record, hospital))
        changed = False
        detail_sources = hospital.setdefault("detailSources", {})
        for field in TARGET_FIELDS:
            value = record.get(field, "")
            if not value:
                continue
            if overwrite or not hospital.get(field):
                if hospital.get(field) != value:
                    hospital[field] = value
                    detail_sources[field] = record["sourceUrl"]
                    stats["filled"][field] += 1
                    changed = True
        if changed:
            hospital["eResidentSourceUrl"] = record["sourceUrl"]
            stats["updatedHospitals"] += 1

    return stats, matched_records


def supplement_youkou(data, matched_records, timeout, workers, overwrite=False):
    targets = [
        record
        for record, hospital in matched_records
        if overwrite or not hospital.get("salary") or not hospital.get("quota")
    ]
    details_by_source = {}
    stats = {"checked": len(targets), "updatedHospitals": 0, "filled": {"salary": 0, "quota": 0}}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_youkou, record, timeout): record for record in targets}
        for index, future in enumerate(as_completed(futures), 1):
            record = futures[future]
            try:
                source, details = future.result()
                details_by_source[source] = details
            except Exception as exc:
                print(f"youkou failed {record['sourceUrl']}: {exc}")
            if index % 50 == 0 or index == len(futures):
                print(f"youkou: {index}/{len(futures)}")

    by_prefecture = index_hospitals(data)
    for record in targets:
        details = details_by_source.get(record["sourceUrl"])
        if not details:
            continue
        hospital, _ = best_match(record, by_prefecture.get(record["prefecture"], data["hospitals"]))
        if not hospital:
            continue
        changed = False
        detail_sources = hospital.setdefault("detailSources", {})
        for field in ("salary", "quota"):
            value = details.get(field, "")
            if not value:
                continue
            if overwrite or not hospital.get(field):
                if hospital.get(field) != value:
                    hospital[field] = value
                    detail_sources[field] = details["sourceUrl"]
                    stats["filled"][field] += 1
                    changed = True
        if changed:
            hospital["eResidentSourceUrl"] = details["sourceUrl"]
            stats["updatedHospitals"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Supplement hospital details from e-resident.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pages", type=int, default=72)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--include-youkou", action="store_true")
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    records = fetch_list_records(args.timeout, args.workers, args.pages)
    stats, matched_records = apply_list_records(data, records, overwrite=args.overwrite)
    youkou_stats = None
    if args.include_youkou:
        youkou_stats = supplement_youkou(
            data,
            matched_records,
            timeout=args.timeout,
            workers=args.workers,
            overwrite=args.overwrite,
        )

    data["eResidentScrapedAt"] = datetime.now(timezone.utc).date().isoformat()
    source = {
        "label": "e-resident 初期研修病院検索（補完データ）",
        "url": LIST_URL,
    }
    if source not in data.get("sources", []):
        data.setdefault("sources", []).append(source)

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"list": stats, "youkou": youkou_stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
