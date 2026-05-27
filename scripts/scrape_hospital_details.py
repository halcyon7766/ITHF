import argparse
import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
USER_AGENT = "ITHF-hospital-search/1.0 (+https://github.com/halcyon7766/ITHF)"
TARGET_FIELDS = ["emergencyCategory", "salary", "quota", "beds"]
DETAIL_KEYWORDS = [
    "初期研修",
    "臨床研修",
    "研修医",
    "卒後",
    "resident",
    "junior",
    "kenshu",
    "sotsugo",
]


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_digits(value):
    table = str.maketrans("０１２３４５６７８９，", "0123456789,")
    return value.translate(table)


def fetch_html(session, url, timeout):
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        return "", response.url
    response.encoding = response.apparent_encoding or response.encoding
    return response.text, response.url


def html_to_text_and_links(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = normalize_space(soup.get_text(" "))
    links = []
    for anchor in soup.find_all("a", href=True):
        label = normalize_space(anchor.get_text(" "))
        href = urljoin(base_url, anchor["href"])
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        combined = f"{label} {href}".lower()
        if any(keyword.lower() in combined for keyword in DETAIL_KEYWORDS):
            links.append(href)
    return text, sorted(set(links), key=rank_detail_link)


def rank_detail_link(url):
    lowered = url.lower()
    score = 0
    for keyword in ["初期研修", "臨床研修", "研修医", "resident", "junior"]:
        if keyword.lower() in lowered:
            score -= 5
    for keyword in ["sotsugo", "kenshu", "卒後"]:
        if keyword.lower() in lowered:
            score -= 3
    return score


def has_training_context(text):
    return bool(
        re.search(
            r"(初期研修|初期臨床研修|臨床研修医|研修医募集|卒後臨床研修|resident|junior|sotsugo)",
            text,
            flags=re.IGNORECASE,
        )
    )


def extract_after_label(text, labels, value_pattern, max_gap=90):
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"({label_pattern})[：:\s　]*.{{0,{max_gap}}}?({value_pattern})")
    match = pattern.search(text)
    if not match:
        return ""
    return normalize_space(match.group(2))


def extract_beds(text):
    value = extract_after_label(
        text,
        ["病床数", "許可病床数", "総病床数", "許可病床"],
        r"[0-9０-９,，]{2,5}\s*床",
        max_gap=50,
    )
    if value:
        return normalize_digits(value).replace(" ", "")
    match = re.search(r"(?:全|総|許可)?病床(?:数)?[^\d０-９]{0,30}([0-9０-９,，]{2,5})\s*床", text)
    if match:
        return f"{normalize_digits(match.group(1))}床"
    match = re.search(r"([0-9０-９,，]{2,5})\s*床[^\s]{0,12}(?:の)?(?:病床|ベッド)", text)
    return f"{normalize_digits(match.group(1))}床" if match else ""


def extract_emergency(text):
    emergency_window = ""
    match = re.search(r".{0,80}(救急指定|救急区分|救急告示|救命救急|二次救急|2次救急|三次救急|3次救急).{0,80}", text)
    if match:
        emergency_window = match.group(0)
    target = emergency_window or text

    if re.search(r"(三次|3次|３次)", target):
        return "3次救急"
    if re.search(r"(二次|2次|２次)", target):
        return "2次救急"
    if re.search(r"(一次|1次|１次)", target):
        return "1次救急"
    if "救命救急センター" in target:
        return "3次救急（救命救急センター）"
    if "救急告示" in target:
        return "次数不明（救急告示）"
    return ""


def extract_quota(text):
    if not has_training_context(text):
        return ""
    value = extract_after_label(
        text,
        ["募集定員", "募集人員", "募集人数", "採用人数", "採用予定人数", "定員"],
        r"[0-9０-９]{1,3}\s*名",
        max_gap=70,
    )
    return normalize_digits(value).replace(" ", "") if value else ""


def extract_salary(text):
    if not has_training_context(text):
        return ""
    labels = ["給与", "給料", "報酬", "研修手当"]
    label_pattern = "|".join(re.escape(label) for label in labels)
    yen = r"(?:月額|年額|1年次|2年次|１年次|２年次)?\s*(?:約)?\s*[0-9０-９,，.．]{2,10}\s*(?:万)?\s*円(?:程度|税込)?"
    pattern = re.compile(rf"({label_pattern}).{{0,80}}?({yen})")
    match = pattern.search(text)
    if match:
        return normalize_space(normalize_digits(match.group(0))[:100])

    section = re.search(rf"({label_pattern}).{{0,100}}", text)
    return normalize_space(section.group(0)) if section else ""


def extract_details(text):
    return {
        "emergencyCategory": extract_emergency(text),
        "salary": extract_salary(text),
        "quota": extract_quota(text),
        "beds": extract_beds(text),
    }


def score_details(details):
    return sum(1 for key in TARGET_FIELDS if details.get(key))


def scrape_one(index, hospital, timeout, max_pages):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    tried = []
    best = {key: "" for key in TARGET_FIELDS}
    field_sources = {}

    try:
        html, final_url = fetch_html(session, hospital["hospitalUrl"], timeout)
        tried.append(final_url)
        if not html:
            return index, best, final_url, "non_html"

        text, links = html_to_text_and_links(html, final_url)
        details = extract_details(text)
        for key, value in details.items():
            if value and not best[key]:
                best[key] = value
                field_sources[key] = final_url

        for url in links[: max(0, max_pages - 1)]:
            if score_details(best) == len(TARGET_FIELDS):
                break
            try:
                html, final_url = fetch_html(session, url, timeout)
                tried.append(final_url)
                if not html:
                    continue
                text, nested_links = html_to_text_and_links(html, final_url)
                details = extract_details(text)
                for key, value in details.items():
                    if value and not best[key]:
                        best[key] = value
                        field_sources[key] = final_url
                for nested in nested_links:
                    if nested not in links and nested not in tried:
                        links.append(nested)
            except Exception:
                continue

        status = "ok" if score_details(best) else "not_found"
        return index, best, field_sources.get("salary") or field_sources.get("quota") or field_sources.get("beds") or field_sources.get("emergencyCategory") or tried[0], status
    except Exception as exc:
        return index, best, hospital["hospitalUrl"], f"error: {type(exc).__name__}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only scrape the first N hospitals")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    hospitals = payload["hospitals"]
    targets = [
        (index, hospital)
        for index, hospital in enumerate(hospitals)
        if args.overwrite or hospital.get("scrapeStatus") in {"", "not_run", None}
    ]
    if args.limit:
        targets = targets[: args.limit]

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(scrape_one, index, hospital, args.timeout, args.max_pages)
            for index, hospital in targets
        ]
        for future in as_completed(futures):
            index, details, source_url, status = future.result()
            hospital = hospitals[index]
            hospital.update(details)
            hospital["scrapeStatus"] = status
            hospital["scrapeSourceUrl"] = source_url
            completed += 1
            if completed % 25 == 0 or completed == len(targets):
                print(f"{completed}/{len(targets)} scraped")

    payload["scrapedAt"] = datetime.now(timezone.utc).date().isoformat()
    DATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = {
        key: sum(1 for hospital in hospitals if hospital.get(key))
        for key in TARGET_FIELDS
    }
    print(f"Scraped {len(targets)} hospitals")
    print(counts)


if __name__ == "__main__":
    main()
