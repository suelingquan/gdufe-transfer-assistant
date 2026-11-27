"""Parse the 2024 transfer-list PDF tables into anonymised statistics data.

Input: JSON table output produced by `workbuddy-pdf -f table --table-format json`.
Output: backend/data/transfer_gpa_2024.json

Only aggregate-useful fields are retained. Student names and full student IDs
are deliberately dropped so the dataset can be committed to a public repo.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def clean(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def parse_gpa(text: str) -> float | None:
    value = clean(text)
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def read_records(tables_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(tables_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows: dict[int, dict[int, str]] = defaultdict(dict)
        for cell in data.get("cells", []):
            rows[cell["row"]][cell["column"]] = cell.get("text", "")

        for row_index in sorted(rows):
            cells = rows[row_index]
            if row_index < 2:  # title + header
                continue
            serial = clean(cells.get(0, ""))
            if not serial.isdigit():  # page footer etc.
                continue
            gpa = parse_gpa(cells.get(7, ""))
            if gpa is None:
                continue
            to_major = clean(cells.get(4, ""))
            if not to_major:
                continue
            records.append(
                {
                    "seq": int(serial),
                    "from_major": clean(cells.get(3, "")),
                    "to_major": to_major,
                    "category": clean(cells.get(5, "")),
                    "choice": clean(cells.get(6, "")),
                    "gpa": round(gpa, 6),
                }
            )
    return records


def summarise(records: list[dict]) -> dict:
    by_major: dict[str, list[float]] = defaultdict(list)
    for record in records:
        by_major[record["to_major"]].append(record["gpa"])

    summary = {}
    for major, values in by_major.items():
        values.sort()
        summary[major] = {
            "count": len(values),
            "min": round(min(values), 4),
            "p25": round(values[max(0, int(len(values) * 0.25) - 1)], 4),
            "median": round(statistics.median(values), 4),
            "p75": round(values[min(len(values) - 1, int(len(values) * 0.75))], 4),
            "max": round(max(values), 4),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tables_dir", type=Path, help="directory with workbuddy-pdf table JSON files")
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "transfer_gpa_2024.json",
    )
    args = parser.parse_args()

    records = read_records(args.tables_dir)
    payload = {
        "title": "2024级普教本科生专业二次选择拟转专业学生名单",
        "year": 2024,
        "note": "匿名化统计：仅保留专业、类别、志愿与绩点；不含姓名和完整学号。名单为拟转专业公示名单，不等同于最终录取结果。",
        "records": records,
        "summary": summarise(records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(records)} anonymised records, {len(payload['summary'])} target majors -> {args.output}")


if __name__ == "__main__":
    main()
