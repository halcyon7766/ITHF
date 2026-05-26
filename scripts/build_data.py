import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "hospitals.json"

PREFECTURES = [
    "北海道",
    "青森",
    "岩手",
    "宮城",
    "秋田",
    "山形",
    "福島",
    "茨城",
    "栃木",
    "群馬",
    "埼玉",
    "千葉",
    "東京",
    "神奈川",
    "新潟",
    "富山",
    "石川",
    "福井",
    "山梨",
    "長野",
    "岐阜",
    "静岡",
    "愛知",
    "三重",
    "滋賀",
    "京都",
    "大阪",
    "兵庫",
    "奈良",
    "和歌山",
    "鳥取",
    "島根",
    "岡山",
    "広島",
    "山口",
    "徳島",
    "香川",
    "愛媛",
    "高知",
    "福岡",
    "佐賀",
    "長崎",
    "熊本",
    "大分",
    "宮崎",
    "鹿児島",
    "沖縄",
]

REGIONS = {
    "北海道": "北海道",
    "青森": "東北",
    "岩手": "東北",
    "宮城": "東北",
    "秋田": "東北",
    "山形": "東北",
    "福島": "東北",
    "茨城": "関東",
    "栃木": "関東",
    "群馬": "関東",
    "埼玉": "関東",
    "千葉": "関東",
    "東京": "関東",
    "神奈川": "関東",
    "新潟": "中部",
    "富山": "中部",
    "石川": "中部",
    "福井": "中部",
    "山梨": "中部",
    "長野": "中部",
    "岐阜": "中部",
    "静岡": "中部",
    "愛知": "中部",
    "三重": "中部",
    "滋賀": "近畿",
    "京都": "近畿",
    "大阪": "近畿",
    "兵庫": "近畿",
    "奈良": "近畿",
    "和歌山": "近畿",
    "鳥取": "中国",
    "島根": "中国",
    "岡山": "中国",
    "広島": "中国",
    "山口": "中国",
    "徳島": "四国",
    "香川": "四国",
    "愛媛": "四国",
    "高知": "四国",
    "福岡": "九州・沖縄",
    "佐賀": "九州・沖縄",
    "長崎": "九州・沖縄",
    "熊本": "九州・沖縄",
    "大分": "九州・沖縄",
    "宮崎": "九州・沖縄",
    "鹿児島": "九州・沖縄",
    "沖縄": "九州・沖縄",
}

SOURCES = [
    {
        "path": ROOT / "sources" / "list2025-daigaku.txt",
        "hospital_type": "大学病院",
        "source_url": "https://www.jrmp2.jp/hospital-list/list2025-daigaku.pdf",
        "expected_count": 125,
    },
    {
        "path": ROOT / "sources" / "list2025-ippan.txt",
        "hospital_type": "臨床研修病院",
        "source_url": "https://www.jrmp2.jp/hospital-list/list2025-ippan.pdf",
        "expected_count": 901,
    },
]


def parse_source(source):
    pref_pattern = "|".join(re.escape(pref) for pref in PREFECTURES)
    row_pattern = re.compile(rf"^({pref_pattern})\s+(.+?)\s+([○◯-])\s+(\d+)\s*$")
    rows = []

    for line in source["path"].read_text(encoding="utf-8").splitlines():
        line = line.strip()
        match = row_pattern.match(line)
        if not match:
            continue

        prefecture, name, participation, reception_number = match.groups()
        rows.append(
            {
                "id": f"2025-{source['hospital_type']}-{reception_number}",
                "year": 2025,
                "type": source["hospital_type"],
                "prefecture": prefecture,
                "region": REGIONS[prefecture],
                "name": " ".join(name.split()),
                "matchingParticipation": participation in {"○", "◯"},
                "receptionNumber": int(reception_number),
                "sourceUrl": source["source_url"],
            }
        )

    if len(rows) != source["expected_count"]:
        raise ValueError(
            f"{source['path'].name}: expected {source['expected_count']} rows, got {len(rows)}"
        )

    return rows


def main():
    hospitals = []
    for source in SOURCES:
        hospitals.extend(parse_source(source))

    payload = {
        "generatedAt": "2026-05-26",
        "datasetYear": 2025,
        "notice": "JRMP参加病院ページでは2026年度一覧が準備中のため、公開済みの2025年度PDF一覧をデータ化しています。",
        "sources": [
            {
                "label": "JRMP 参加病院一覧ページ",
                "url": "https://www.jrmp2.jp/sanka-hospital.html",
            },
            {
                "label": "2025年度 大学病院一覧PDF",
                "url": "https://www.jrmp2.jp/hospital-list/list2025-daigaku.pdf",
            },
            {
                "label": "2025年度 臨床研修病院一覧PDF",
                "url": "https://www.jrmp2.jp/hospital-list/list2025-ippan.pdf",
            },
        ],
        "hospitals": hospitals,
    }

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(hospitals)} hospitals to {OUTPUT}")


if __name__ == "__main__":
    main()
