import argparse
import json
import re
import warnings
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from pypdf import PdfReader


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
USER_AGENT = "ITHF-hospital-search/1.0 (+https://github.com/halcyon7766/ITHF)"
TARGET_FIELDS = ["emergencyCategory", "salary", "quota", "beds"]
UNAVAILABLE = "公開情報なし"
DETAIL_KEYWORDS = [
    "初期研修",
    "初期臨床研修",
    "臨床研修",
    "臨床研修医",
    "研修医",
    "卒後",
    "resident",
    "residency",
    "junior",
    "kenshu",
    "kensyuu",
    "rinsho",
    "rinsyo",
    "sotsugo",
    "program",
]
DETAIL_FOLLOWUP_KEYWORDS = [
    "募集要項",
    "募集案内",
    "処遇",
    "待遇",
    "給与",
    "プログラム",
    "application",
    "treatment",
    "youkou",
    "boshu",
    "pdf",
]
CRAWL_ONLY_KEYWORDS = [
    "採用",
    "採用情報",
    "recruit",
    "recruitment",
    "employment",
    "saiyo",
]
EXCLUDED_DETAIL_KEYWORDS = [
    "歯科",
    "歯科研修",
    "歯科医",
    "dent",
    "dental",
    "shika",
    "後期研修",
    "後期臨床研修",
    "専攻医",
    "専門研修",
    "senior",
    "latter",
    "kouki",
    "gijutusyoku",
    "技術職",
    "看護",
    "nurse",
]


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_digits(value):
    table = str.maketrans("０１２３４５６７８９，", "0123456789,")
    return value.translate(table)


def pdf_bytes_to_text(content):
    try:
        reader = PdfReader(BytesIO(content))
        return normalize_space(" ".join(page.extract_text() or "" for page in reader.pages))
    except Exception:
        return ""


def fetch_document(session, url, timeout):
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    final_url = response.url
    if "pdf" in content_type.lower() or urlparse(final_url).path.lower().endswith(".pdf"):
        return pdf_bytes_to_text(response.content), final_url, []
    response.encoding = response.apparent_encoding or response.encoding
    text, links = html_to_text_and_links(response.text, final_url)
    return text, final_url, links


def html_to_text_and_links(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = normalize_space(soup.get_text(" "))
    links = []
    base_host = urlparse(base_url).netloc
    for anchor in soup.find_all("a", href=True):
        label = normalize_space(anchor.get_text(" "))
        href = urljoin(base_url, anchor["href"])
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        same_host = parsed.netloc == base_host
        combined = f"{label} {href}".lower()
        if is_excluded_detail_target(combined):
            continue
        has_detail_keyword = any(keyword.lower() in combined for keyword in DETAIL_KEYWORDS)
        has_followup_keyword = any(keyword.lower() in combined for keyword in DETAIL_FOLLOWUP_KEYWORDS)
        has_crawl_only_keyword = same_host and any(
            keyword.lower() in combined for keyword in CRAWL_ONLY_KEYWORDS
        )
        if has_detail_keyword or (has_training_context(text) and has_followup_keyword) or has_crawl_only_keyword:
            links.append(href)
    return text, sorted(set(links), key=rank_detail_link)


def rank_detail_link(url):
    lowered = url.lower()
    score = 0
    for keyword in ["初期研修", "初期臨床研修", "臨床研修医", "resident", "junior"]:
        if keyword.lower() in lowered:
            score -= 5
    for keyword in ["sotsugo", "kenshu", "kensyuu", "rinsho", "rinsyo", "卒後"]:
        if keyword.lower() in lowered:
            score -= 3
    for keyword in ["募集要項", "処遇", "待遇", "給与", "program", ".pdf"]:
        if keyword.lower() in lowered:
            score -= 2
    for keyword in CRAWL_ONLY_KEYWORDS:
        if keyword.lower() in lowered:
            score += 4
    return score


def is_excluded_detail_target(value):
    lowered = value.lower()
    return any(keyword.lower() in lowered for keyword in EXCLUDED_DETAIL_KEYWORDS)


def is_crawl_only_target(value):
    lowered = value.lower()
    has_crawl_keyword = any(keyword.lower() in lowered for keyword in CRAWL_ONLY_KEYWORDS)
    has_detail_keyword = any(keyword.lower() in lowered for keyword in DETAIL_KEYWORDS)
    return has_crawl_keyword and not has_detail_keyword


def is_missing_detail(value):
    return not value or value == UNAVAILABLE


def has_training_context(text):
    return bool(
        re.search(
            r"(初期研修|初期臨床研修|臨床研修医|研修医募集|卒後臨床研修|resident|junior|sotsugo|臨床研修プログラム)",
            text,
            flags=re.IGNORECASE,
        )
    )


def has_training_context_near(text, start, end, radius=500):
    window = text[max(0, start - radius) : min(len(text), end + radius)]
    return has_training_context(window) and not is_excluded_detail_target(window)


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
        r"[0-9０-９][0-9０-９,，]{1,4}\s*床",
        max_gap=50,
    )
    if value:
        normalized = normalize_digits(value).replace(" ", "")
        number = int(re.sub(r"\D", "", normalized))
        return normalized if 20 <= number <= 2000 else ""
    match = re.search(r"(?:全|総|許可)?病床(?:数)?[^\d０-９]{0,30}(?<![0-9０-９,，])([0-9０-９][0-9０-９,，]{1,4})\s*床", text)
    if match:
        number = int(re.sub(r"\D", "", normalize_digits(match.group(1))))
        return f"{normalize_digits(match.group(1))}床" if 20 <= number <= 2000 else ""
    match = re.search(r"(?<![0-9０-９,，])([0-9０-９][0-9０-９,，]{1,4})\s*床[^\s]{0,12}(?:の)?(?:病床|ベッド)", text)
    if not match:
        return ""
    number = int(re.sub(r"\D", "", normalize_digits(match.group(1))))
    return f"{normalize_digits(match.group(1))}床" if 20 <= number <= 2000 else ""


def extract_emergency(text):
    emergency_window = ""
    match = re.search(r".{0,80}(救急指定|救急区分|救急告示|救命救急|二次救急|2次救急|三次救急|3次救急).{0,80}", text)
    if match:
        emergency_window = match.group(0)
    target = emergency_window or text

    if re.search(r"(第三次|第3次|第３次|三次|3次|３次)\s*救急", target):
        return "3次救急"
    if re.search(r"(第二次|第2次|第２次|二次|2次|２次)\s*救急", target):
        return "2次救急"
    if re.search(r"(第一次|第1次|第１次|一次|1次|１次)\s*救急", target):
        return "1次救急"
    if "救命救急センター" in target:
        return "3次救急（救命救急センター）"
    if "救急告示" in target:
        return "次数不明（救急告示）"
    return ""


def extract_quota(text):
    labels = ["募集定員", "募集人員", "募集人数", "採用人数", "採用予定人数", "採用定員", "定員", "基幹型", "プログラム定員"]
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"({label_pattern})[：:\s　]*.{{0,80}}?([0-9０-９]{{1,3}}\s*名)")
    for match in pattern.finditer(text):
        if has_training_context_near(text, match.start(), match.end()):
            value = normalize_digits(match.group(2)).replace(" ", "")
            number_match = re.search(r"\d+", value)
            if number_match and int(number_match.group(0)) <= 100:
                return value
    return ""


def extract_salary(text):
    labels = ["給与", "給料", "報酬", "研修手当"]
    label_pattern = "|".join(re.escape(label) for label in labels)
    yen = r"(?:月額|年額|1年次|2年次|１年次|２年次)?\s*(?:約)?\s*[0-9０-９,，.．]{2,10}\s*(?:万)?\s*円(?:程度|税込)?"
    pattern = re.compile(rf"({label_pattern}).{{0,80}}?({yen})")
    for match in pattern.finditer(text):
        if has_training_context_near(text, match.start(), match.end()):
            return normalize_space(normalize_digits(match.group(0))[:100])

    return ""


def extract_details(text):
    return {
        "emergencyCategory": extract_emergency(text),
        "salary": extract_salary(text),
        "quota": extract_quota(text),
        "beds": extract_beds(text),
    }


def score_details(details):
    return sum(1 for key in TARGET_FIELDS if not is_missing_detail(details.get(key)))


def scrape_one(index, hospital, timeout, max_pages, preserve_existing):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    tried = []
    if preserve_existing:
        best = {
            key: "" if is_missing_detail(hospital.get(key, "")) else hospital.get(key, "")
            for key in TARGET_FIELDS
        }
    else:
        best = {key: "" for key in TARGET_FIELDS}
    field_sources = {}

    try:
        text, final_url, links = fetch_document(session, hospital["hospitalUrl"], timeout)
        tried.append(final_url)
        if not text:
            return index, best, final_url, "non_html"

        details = extract_details(text)
        for key, value in details.items():
            if value and is_missing_detail(best[key]):
                best[key] = value
                field_sources[key] = final_url

        for url in links[: max(0, max_pages - 1)]:
            if score_details(best) == len(TARGET_FIELDS):
                break
            if is_excluded_detail_target(url):
                continue
            try:
                text, final_url, nested_links = fetch_document(session, url, timeout)
                tried.append(final_url)
                if not text:
                    continue
                if not is_crawl_only_target(url) or has_training_context(text):
                    details = extract_details(text)
                    for key, value in details.items():
                        if value and is_missing_detail(best[key]):
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
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Scrape hospitals that are missing at least one detail field, preserving existing values",
    )
    args = parser.parse_args()

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    hospitals = payload["hospitals"]
    if args.overwrite:
        targets = list(enumerate(hospitals))
    elif args.missing_only:
        targets = [
            (index, hospital)
            for index, hospital in enumerate(hospitals)
            if any(is_missing_detail(hospital.get(key)) for key in TARGET_FIELDS)
        ]
    else:
        targets = [
            (index, hospital)
            for index, hospital in enumerate(hospitals)
            if hospital.get("scrapeStatus") in {"", "not_run", None}
        ]
    if args.limit:
        targets = targets[: args.limit]

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                scrape_one,
                index,
                hospital,
                args.timeout,
                args.max_pages,
                not args.overwrite,
            )
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
