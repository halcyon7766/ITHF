import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hospitals.json"
TARGET_FIELDS = ("emergencyCategory", "salary", "quota", "beds")
UNAVAILABLE = "公開情報なし"


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    counts = {field: 0 for field in TARGET_FIELDS}

    for hospital in data["hospitals"]:
        detail_sources = hospital.setdefault("detailSources", {})
        fallback_source = (
            hospital.get("scrapeSourceUrl")
            or hospital.get("hospitalUrl")
            or hospital.get("sourceUrl")
            or ""
        )
        for field in TARGET_FIELDS:
            if hospital.get(field):
                continue
            hospital[field] = UNAVAILABLE
            if fallback_source:
                detail_sources[field] = fallback_source
            counts[field] += 1

    data["missingFinalizedAt"] = datetime.now(timezone.utc).date().isoformat()
    data["missingFinalizedValue"] = UNAVAILABLE
    data["missingFinalizedCounts"] = counts

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
