import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scrape_eresident_details import normalize_beds, normalize_quota
from scrape_reginavi_details import PREFECTURES, TARGET_FIELDS, best_match, clean_text, normalize_emergency


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
BASE_URL = "https://www.dnavi.jp"
LIST_URL = f"{BASE_URL}/hospital/"
USER_AGENT = "Mozilla/5.0 (compatible; ITHF-hospital-search/1.0; +https://github.com/halcyon7766/ITHF)"


def make_session(timeout):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.request_timeout = timeout
    return session


def get(session, url):
    response = session.get(url, timeout=session.request_timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text, response.url


def parse_prefecture_and_emergency(card):
    for row in card.select(".row"):
        smalls = [clean_text(node.get_text(" ", strip=True)) for node in row.select("small")]
        for index, text in enumerate(smalls):
            if text in PREFECTURES and index + 1 < len(smalls):
                emergency = normalize_emergency(smalls[index + 1])
                if emergency:
                    return text, emergency
    return "", ""


def parse_metric(card, label):
    for wrapper in card.select(".col-24"):
        label_node = wrapper.select_one(".text-primary")
        value_node = wrapper.select_one("p")
        if not label_node or not value_node:
            continue
        if label in clean_text(label_node.get_text(" ", strip=True)):
            return clean_text(value_node.get_text(" ", strip=True))
    return ""


def parse_list_page(html):
    soup = BeautifulSoup(html, "lxml")
    records = []
    for card in soup.select("#hospitals_list .card-hosp"):
        name_node = card.select_one(".card-hosp-name")
        link_node = card.select_one('a[href^="/hospital/"]')
        if not name_node or not link_node:
            continue

        prefecture, emergency = parse_prefecture_and_emergency(card)
        records.append(
            {
                "prefecture": prefecture,
                "name": clean_text(name_node.get_text(" ", strip=True)),
                "sourceUrl": urljoin(BASE_URL, link_node.get("href")),
                "quota": normalize_quota(parse_metric(card, "募集人数")),
                "beds": normalize_beds(parse_metric(card, "病床数")),
                "salary": "",
                "emergencyCategory": emergency,
            }
        )
    return records


def fetch_list_page(page, timeout):
    session = make_session(timeout)
    url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
    html, _ = get(session, url)
    return parse_list_page(html)


def fetch_records(timeout, workers, pages):
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


def apply_records(data, records, overwrite=False):
    by_prefecture = {}
    for hospital in data["hospitals"]:
        by_prefecture.setdefault(hospital["prefecture"], []).append(hospital)

    stats = {
        "records": len(records),
        "matched": 0,
        "ambiguousOrUnmatched": 0,
        "updatedHospitals": 0,
        "filled": {field: 0 for field in TARGET_FIELDS},
    }

    for record in records:
        candidates = by_prefecture.get(record["prefecture"], data["hospitals"])
        hospital, _ = best_match(record, candidates)
        if not hospital:
            stats["ambiguousOrUnmatched"] += 1
            continue

        stats["matched"] += 1
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
            hospital["dnaviSourceUrl"] = record["sourceUrl"]
            stats["updatedHospitals"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Supplement hospital details from Ishi Navi.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pages", type=int, default=54)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    records = fetch_records(args.timeout, args.workers, args.pages)
    stats = apply_records(data, records, overwrite=args.overwrite)
    data["dnaviScrapedAt"] = datetime.now(timezone.utc).date().isoformat()
    source = {
        "label": "医師ナビ 初期研修病院検索（補完データ）",
        "url": LIST_URL,
    }
    if source not in data.get("sources", []):
        data.setdefault("sources", []).append(source)

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
