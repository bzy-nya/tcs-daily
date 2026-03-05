from __future__ import annotations

import argparse
import json
from pathlib import Path


def search_history_issues(query: str, posts_dir: Path | None = None) -> list[dict[str, str]]:
    posts_dir = posts_dir or Path(__file__).resolve().parents[4] / "posts"
    results: list[dict[str, str]] = []
    needle = query.lower()
    for path in sorted(posts_dir.glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if needle in text.lower():
            results.append(
                {
                    "path": str(path.relative_to(posts_dir.parent)),
                    "title": path.stem,
                    "matched_query": query,
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Search existing generated posts.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--posts-dir", default="posts")
    args = parser.parse_args()
    payload = search_history_issues(args.query, Path(args.posts_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
