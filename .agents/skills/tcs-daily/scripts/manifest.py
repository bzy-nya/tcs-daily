from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "reports": []}
    return json.loads(path.read_text(encoding="utf-8"))


def upsert_report(manifest: dict[str, Any], report_entry: dict[str, Any]) -> dict[str, Any]:
    reports = [item for item in manifest.get("reports", []) if item.get("date") != report_entry.get("date")]
    reports.append(report_entry)
    reports.sort(key=lambda item: item["date"], reverse=True)
    manifest["version"] = 1
    manifest["reports"] = reports
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert posts/manifest.json with one report entry.")
    parser.add_argument("--manifest", default="posts/manifest.json")
    parser.add_argument("--date", required=True)
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--paper-count", required=True, type=int)
    parser.add_argument("--source-path", required=True, help="Path to JSON file with selected paper metadata.")
    parser.add_argument("--category", action="append", default=[])
    args = parser.parse_args()

    source_path = Path(args.source_path)
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    report_entry = {
        "date": args.date,
        "path": args.report_path,
        "paper_count": args.paper_count,
        "category_summary": args.category,
        "source_path": str(source_path),
        "papers": source_payload.get("papers", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    write_manifest(manifest_path, upsert_report(manifest, report_entry))
    print(json.dumps({"manifest_path": str(manifest_path), "report": report_entry}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

