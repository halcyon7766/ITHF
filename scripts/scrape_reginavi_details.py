import argparse
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
BASE_URL = "https://www.residentnavi.com"
USER_AGENT = "Mozilla/5.0 (compatible; ITHF-hospital-search/1.0; +https://github.com/halcyon7766/ITHF)"
TARGET_FIELDS = ("quota", "beds", "salary", "emergencyCategory")

SC_PAGES = [
    ("和歌山", "wakayama"),
    ("石川", "Ishikawa"),
    ("岐阜", "gifu-resident"),
    ("", "kkr"),
    ("神奈川", "shonankamakura"),
    ("徳島", "tokushima_miyoshi"),
    ("茨城", "ushiku_aiwa"),
    ("香川", "kagawa"),
    ("徳島", "tokushima"),
    ("埼玉", "saitama"),
]

NOISE_WORDS = [
    "医療法人社団",
    "社会医療法人",
    "公益財団法人",
    "一般財団法人",
    "一般社団法人",
    "独立行政法人",
    "地方独立行政法人",
    "国立研究開発法人",
    "国立病院機構",
    "地域医療機能推進機構",
    "労働者健康安全機構",
    "国家公務員共済組合連合会",
    "全国土木建築国民健康保険組合",
    "厚生農業協同組合連合会",
    "厚生連",
    "日本赤十字社",
    "済生会",
    "医療法人",
    "学校法人",
    "社会福祉法人",
    "市立",
    "県立",
    "公立",
    "国保",
    "JA",
    "JCHO",
]


def clean_text(value):
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalize_name(value):
    text = unicodedata.normalize("NFKC", value).lower()
    text = re.sub(r"[ 　\t\r\n・･,，.．()（）「」『』【】\[\]／/\\\-ー_]", "", text)
    for word in NOISE_WORDS:
        text = text.replace(unicodedata.normalize("NFKC", word).lower(), "")
    return text


def normalize_detail(value):
    return clean_text(value.replace("\n", " "))


def normalize_emergency(text):
    compact = re.sub(r"\s+", "", text)
    if "救命救急センター" in compact or "高度救命救急" in compact:
        return "3次救急（救命救急センター）"
    if re.search(r"(三次|3次|３次)救急", compact):
        return "3次救急"
    if re.search(r"(二次|2次|２次)救急", compact):
        return "2次救急"
    if re.search(r"(一次|1次|１次)救急", compact):
        return "1次救急"
    return ""


def extract_labeled_value(text, label_patterns):
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines):
        if any(re.search(pattern, line) for pattern in label_patterns):
            same_line = re.sub("|".join(label_patterns), "", line).strip(" :：")
            if same_line:
                return normalize_detail(same_line)
            for candidate in lines[index + 1 : index + 4]:
                if candidate and not any(re.search(pattern, candidate) for pattern in label_patterns):
                    return normalize_detail(candidate)
    return ""


def parse_heading_name(text):
    text = clean_text(text)
    match = re.match(r"^[0-9０-９]+[.\s　]*(.+)$", text)
    if not match:
        return ""
    name = clean_text(match.group(1))
    if not re.search(r"(病院|医療センター|総合医療センター|赤十字|労災|医療機構)", name):
        return ""
    if re.search(r"(MAP|マップ|一覧|情報|紹介)$", name):
        return ""
    return name


def collect_section(heading):
    texts = []
    links = []
    for sibling in heading.next_siblings:
        sibling_name = getattr(sibling, "name", None)
        if sibling_name in {"h2", "h3", "h4"} and parse_heading_name(sibling.get_text(" ", strip=True)):
            break
        if not hasattr(sibling, "get_text"):
            continue
        texts.append(sibling.get_text("\n", strip=True))
        for link in sibling.find_all("a", href=True):
            links.append(link["href"])
    return "\n".join(texts), links


def parse_generic_records(prefecture, soup, source_url):
    records = []
    seen = set()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        name = parse_heading_name(heading.get_text(" ", strip=True))
        if not name:
            continue
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)

        section_text, links = collect_section(heading)
        if not section_text:
            continue

        source = source_url
        for href in links:
            if "/hospitals/" in href:
                source = urljoin(BASE_URL, href)
                break

        emergency_text = extract_labeled_value(section_text, [r"救急指定", r"救急区分"])
        record = {
            "prefecture": prefecture,
            "name": name,
            "sourceUrl": source,
            "quota": extract_labeled_value(section_text, [r"募集定員", r"募集定員数"]),
            "beds": extract_labeled_value(section_text, [r"病床数"]),
            "salary": extract_labeled_value(section_text, [r"総年収", r"給与", r"給料"]),
            "emergencyCategory": normalize_emergency(emergency_text),
        }
        if any(record[field] for field in TARGET_FIELDS):
            records.append(record)
    return records


def dedupe_records(records):
    deduped = {}
    for record in records:
        key = (record["prefecture"], normalize_name(record["name"]))
        current = deduped.get(key)
        if not current:
            deduped[key] = record
            continue
        for field in TARGET_FIELDS:
            if not current.get(field) and record.get(field):
                current[field] = record[field]
        if current["sourceUrl"] == BASE_URL and record["sourceUrl"] != BASE_URL:
            current["sourceUrl"] = record["sourceUrl"]
    return list(deduped.values())


def parse_reginavi_page(prefecture, html, source_url):
    soup = BeautifulSoup(html, "lxml")
    records = []
    for box in soup.select(".m_hospital-box"):
        name_node = box.select_one(".title .name") or box.select_one(".name")
        if not name_node:
            continue

        source_node = box.select_one("a.web")
        record = {
            "prefecture": prefecture,
            "name": clean_text(name_node.get_text(" ", strip=True)),
            "sourceUrl": urljoin(BASE_URL, source_node.get("href")) if source_node else source_url,
            "quota": "",
            "beds": "",
            "salary": "",
            "emergencyCategory": "",
        }

        for dl in box.select(".detail-info02 dl"):
            label_node = dl.select_one("dt")
            value_node = dl.select_one("dd")
            if not label_node or not value_node:
                continue

            label = clean_text(label_node.get_text(" ", strip=True))
            value = normalize_detail(value_node.get_text(" ", strip=True))
            if "募集定員" in label:
                record["quota"] = value
            elif label == "病床数":
                record["beds"] = value
            elif "総年収" in label or "給与" in label:
                record["salary"] = value
            elif "救急区分" in label or "救急指定" in label:
                record["emergencyCategory"] = normalize_emergency(value)

        block_emergency = normalize_emergency(box.get_text(" ", strip=True))
        if block_emergency and not record["emergencyCategory"]:
            record["emergencyCategory"] = block_emergency

        records.append(record)
    records.extend(parse_generic_records(prefecture, soup, source_url))
    return dedupe_records(records)


def fetch_page(prefecture, slug, timeout):
    url = f"{BASE_URL}/sc/{slug}"
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_reginavi_page(prefecture, response.text, url)


def best_match(record, candidates):
    source_name = normalize_name(record["name"])
    if not source_name:
        return None, 0

    scored = []
    for hospital in candidates:
        target_name = normalize_name(hospital["name"])
        if not target_name:
            continue

        if source_name == target_name:
            score = 1.0
        elif source_name in target_name or target_name in source_name:
            score = 0.94 + min(len(source_name), len(target_name)) / max(len(source_name), len(target_name)) * 0.05
        else:
            score = SequenceMatcher(None, source_name, target_name).ratio()
        scored.append((score, hospital))

    if not scored:
        return None, 0

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, hospital = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    if best_score >= 0.90 and best_score - second_score >= 0.02:
        return hospital, best_score
    return None, best_score


def apply_records(data, records, overwrite=False):
    by_prefecture = {}
    for hospital in data["hospitals"]:
        by_prefecture.setdefault(hospital["prefecture"], []).append(hospital)
    all_hospitals = data["hospitals"]

    stats = {
        "records": len(records),
        "matched": 0,
        "ambiguousOrUnmatched": 0,
        "updatedHospitals": 0,
        "filled": {field: 0 for field in TARGET_FIELDS},
    }
    unmatched = []

    for record in records:
        candidates = by_prefecture.get(record["prefecture"], []) if record["prefecture"] else all_hospitals
        hospital, score = best_match(record, candidates)
        if not hospital:
            stats["ambiguousOrUnmatched"] += 1
            unmatched.append({"prefecture": record["prefecture"], "name": record["name"], "score": round(score, 3)})
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
            hospital["reginaviSourceUrl"] = record["sourceUrl"]
            stats["updatedHospitals"] += 1

    return stats, unmatched


def main():
    parser = argparse.ArgumentParser(description="Supplement hospital details from RegiNavi prefecture pages.")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--overwrite", action="store_true", help="Replace existing values with RegiNavi values.")
    parser.add_argument("--unmatched", type=Path, default=None, help="Optional JSON path for unmatched records.")
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_page, prefecture, slug, args.timeout): slug
            for prefecture, slug in SC_PAGES
        }
        for future in as_completed(futures):
            slug = futures[future]
            try:
                pref_records = future.result()
            except Exception as exc:
                print(f"{slug}: failed: {exc}")
                continue
            print(f"{slug}: {len(pref_records)} records")
            records.extend(pref_records)

    stats, unmatched = apply_records(data, records, overwrite=args.overwrite)
    data["reginaviScrapedAt"] = datetime.now(timezone.utc).date().isoformat()
    data["reginaviSource"] = "https://www.residentnavi.com/sc"
    reginavi_source = {
        "label": "民間医局レジナビ 研修の現場特集（補完データ）",
        "url": "https://www.residentnavi.com/sc",
    }
    if reginavi_source not in data.get("sources", []):
        data.setdefault("sources", []).append(reginavi_source)

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.unmatched:
        args.unmatched.write_text(json.dumps(unmatched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
