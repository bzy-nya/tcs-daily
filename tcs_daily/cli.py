"""CLI — tool interface for Codex.

Every subcommand prints JSON to stdout, errors to stderr.
Codex calls these tools and decides what to do with the results.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date as date_type
from pathlib import Path

from .config import Config
from .tags import category_defs, normalize_tags, tag_color, tag_defs


ISSUE_RE = re.compile(
    r"^::::issue(?:\[([^\]]*)\])?\s*\n(.*?)^::::\s*$",
    re.MULTILINE | re.DOTALL,
)
ISSUE_LINE_RE = re.compile(r"^::::issue(?:\[([^\]]*)\])?\s*$")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _out(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _err(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    raise SystemExit(1)


def _parse_issue_tags(raw: str | None) -> list[str]:
    tags = [t.strip() for t in (raw or "").split(",") if t.strip()]
    normalized, _unknown = normalize_tags(tags)
    return normalized


def _iter_issue_blocks(md_text: str):
    for match in ISSUE_RE.finditer(md_text):
        yield _parse_issue_tags(match.group(1)), match.group(2)


def _is_report_markdown_link(href: str) -> bool:
    href = href.strip()
    if href.startswith("#"):
        return False
    return bool(
        re.match(r"^(?:\.\./)?posts/\d{4}-\d{2}-\d{2}\.md(?:[#?].*)?$", href)
        or re.match(r"^\d{4}-\d{2}-\d{2}\.md(?:[#?].*)?$", href)
    )


# ═══════════════════════════════════════════════════════════════
#  Data tools
# ═══════════════════════════════════════════════════════════════


def cmd_fetch(args: argparse.Namespace, cfg: Config) -> None:
    """Fetch candidates from arXiv recent listings + metadata (all cached)."""
    from .fetch import fetch_arxiv_metadata, fetch_recent_arxiv

    entries = fetch_recent_arxiv(args.date, cfg.paths)
    papers: list[dict] = []
    for entry in entries:
        try:
            meta = fetch_arxiv_metadata(
                entry["arxiv_id"], cfg.paths, hint=entry
            )
            papers.append({**entry, **meta})
            time.sleep(0.3)
        except Exception as exc:
            papers.append({**entry, "metadata_error": str(exc)})
    _out({"date": args.date, "count": len(papers), "papers": papers})


def cmd_metadata(args: argparse.Namespace, cfg: Config) -> None:
    """Fetch arXiv metadata for one paper (cached)."""
    from .fetch import fetch_arxiv_metadata

    _out(fetch_arxiv_metadata(args.arxiv_id, cfg.paths))


def cmd_download(args: argparse.Namespace, cfg: Config) -> None:
    """Download PDF for one paper (cached)."""
    from .pdf import download

    url = args.url
    if not url:
        cache = cfg.paths.arxiv_cache(args.arxiv_id)
        if cache.exists():
            from .cache import read_json

            url = read_json(cache).get("pdf_url", "")
    if not url:
        url = f"https://arxiv.org/pdf/{args.arxiv_id}.pdf"

    path = download(args.arxiv_id, url, cfg.paths)
    _out(
        {
            "arxiv_id": args.arxiv_id,
            "pdf_path": str(path.relative_to(cfg.paths.root)),
        }
    )


def cmd_extract(args: argparse.Namespace, cfg: Config) -> None:
    """Extract sections from a downloaded PDF (cached)."""
    from .pdf import extract

    _out(extract(args.arxiv_id, cfg.paths))


def cmd_history(args: argparse.Namespace, cfg: Config) -> None:
    """Keyword search over existing report files."""
    posts = cfg.paths.posts
    needle = args.query.lower()
    results: list[dict] = []
    for path in sorted(posts.glob("*.md"), reverse=True):
        text = path.read_text("utf-8", errors="ignore")
        if needle in text.lower():
            title = path.stem
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            results.append(
                {"path": f"posts/{path.name}", "date": path.stem, "title": title}
            )
    _out(results)


def cmd_tags(args: argparse.Namespace, cfg: Config) -> None:
    defs = tag_defs()
    cats = category_defs()
    payload = {
        "categories": [
            {
                "key": key,
                "name": info["name"],
                "order": info["order"],
                "tags": [
                    {"key": tag, **defs[tag]}
                    for tag, tag_info in defs.items()
                    if tag_info["category"] == key
                ],
            }
            for key, info in cats.items()
        ],
        "tags": defs,
    }
    _out(payload)


def cmd_manifest(args: argparse.Namespace, cfg: Config) -> None:
    """Upsert one entry in posts/manifest.json.

    Parses the report markdown to extract papers and tags from
    ::::issue[tags] blocks, so manifest always matches the rendered report.
    """
    from datetime import datetime, timezone

    from .cache import read_json, write_json

    mp = cfg.paths.manifest_file()
    if mp.exists() and mp.read_text("utf-8").strip():
        manifest = read_json(mp)
    else:
        manifest = {"version": 1, "tags": {}, "reports": []}

    # ── Parse markdown for canonical paper/tag info ─────────────
    report_path = cfg.paths.root / args.path
    papers_list: list[dict] = []
    if report_path.exists():
        md_text = report_path.read_text("utf-8")
        for tags, body in _iter_issue_blocks(md_text):
            # Title = first ## heading, strip trailing arXiv link
            title_m = re.search(r"^##\s+(.+)", body, re.MULTILINE)
            raw_title = title_m.group(1).strip() if title_m else ""
            title = re.sub(
                r"\s*\[arXiv:[^\]]*\]\([^)]*\)\s*$", "", raw_title,
            ).strip()
            # arXiv id from first [arXiv:...] link
            arxiv_m = re.search(r"\[arXiv:(\S+?)\]", body)
            arxiv_id = arxiv_m.group(1) if arxiv_m else ""
            paper: dict = {}
            if arxiv_id:
                paper["arxiv_id"] = arxiv_id
            if title:
                paper["title"] = title
            if tags:
                paper["tags"] = tags
            papers_list.append(paper)

    # Fall back to memory.db if markdown parsing yielded nothing
    if not papers_list:
        from .memory import Memory

        mem = Memory(cfg.paths.memory_db)
        mem_papers = mem.get_papers_by_date(args.date)
        papers_list = [
            {"arxiv_id": p["arxiv_id"], "title": p.get("title", ""),
             **({"tags": p["tags"]} if p.get("tags") else {})}
            for p in mem_papers
        ]
        mem.close()

    # ── Derive report-level tags ───────────────────────────────
    report_tags = list(dict.fromkeys(
        t for p in papers_list for t in p.get("tags", [])
    ))

    known_tag_defs = tag_defs()
    manifest["categories"] = category_defs()

    entry = {
        "date": args.date,
        "path": args.path,
        "paper_count": len(papers_list) if papers_list else args.paper_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if report_tags:
        entry["tags"] = report_tags
    if papers_list:
        entry["papers"] = papers_list

    reports = [r for r in manifest.get("reports", []) if r.get("date") != args.date]
    reports.append(entry)
    reports.sort(key=lambda r: r["date"], reverse=True)
    manifest["reports"] = reports

    used_tags = list(dict.fromkeys(
        t
        for report in reports
        for t in (
            list(report.get("tags", []))
            + [tag for paper in report.get("papers", []) for tag in paper.get("tags", [])]
        )
    ))
    manifest["tags"] = {
        tag: {
            "name": known_tag_defs.get(tag, {}).get("name", tag.replace("-", " ").title()),
            "color": tag_color(
                tag,
                known_tag_defs.get(tag, {}).get("category", "uncategorized"),
            ),
            "category": known_tag_defs.get(tag, {}).get("category", "uncategorized"),
        }
        for tag in used_tags
    }

    write_json(mp, manifest)
    _out({"ok": True, "manifest_path": str(mp), "entry": entry})


# ═══════════════════════════════════════════════════════════════
#  Validate
# ═══════════════════════════════════════════════════════════════


def cmd_validate(args: argparse.Namespace, cfg: Config) -> None:
    """Minimal validation — report exists, manifest has entry, frontmatter ok."""
    from .cache import read_json

    errors: list[str] = []

    rp = cfg.paths.report_file(args.date)
    if not rp.exists():
        errors.append(f"Missing report: {rp}")
    elif rp.stat().st_size < 50:
        errors.append(f"Report file too small: {rp}")
    else:
        text = rp.read_text("utf-8")
        if not text.startswith("---"):
            errors.append("Report missing YAML frontmatter")
        elif f"date: {args.date}" not in text.split("---")[1]:
            errors.append("Frontmatter missing correct date field")

        known_tags = tag_defs()
        for lineno, line in enumerate(text.splitlines(), start=1):
            issue_match = ISSUE_LINE_RE.match(line)
            if not issue_match:
                for href in MD_LINK_RE.findall(line):
                    if _is_report_markdown_link(href):
                        errors.append(
                            f"Line {lineno}: report link must use hash route, not {href}"
                        )
                continue

            raw_tags = [t.strip() for t in (issue_match.group(1) or "").split(",") if t.strip()]
            tags, unknown = normalize_tags(raw_tags)
            if not tags:
                errors.append(f"Line {lineno}: issue block must have 1-2 canonical tags")
            if len(tags) > 2:
                errors.append(f"Line {lineno}: issue block has {len(tags)} tags; max is 2")
            for raw in raw_tags:
                canonical = normalize_tags([raw])[0][0] if raw else ""
                if canonical != raw:
                    errors.append(
                        f"Line {lineno}: non-canonical tag `{raw}`; use `{canonical}`"
                    )
            for tag in unknown:
                if tag not in known_tags:
                    errors.append(f"Line {lineno}: unknown tag `{tag}`")

    mp = cfg.paths.manifest_file()
    if not mp.exists() or not mp.read_text("utf-8").strip():
        errors.append("Manifest missing or empty")
    else:
        manifest = read_json(mp)
        match = next(
            (r for r in manifest.get("reports", []) if r["date"] == args.date),
            None,
        )
        if not match:
            errors.append(f"Manifest has no entry for {args.date}")

    _out({"ok": not errors, "errors": errors})
    if errors:
        raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════
#  Memory subcommands
# ═══════════════════════════════════════════════════════════════


def _mem(cfg: Config):
    from .memory import Memory

    return Memory(cfg.paths.memory_db)


def cmd_mem_search(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    _out(m.search_papers(args.query, limit=args.limit))
    m.close()


def cmd_mem_topics(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    if args.query:
        _out(m.search_topics(args.query))
    else:
        _out(m.get_all_topics())
    m.close()


def cmd_mem_entries(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    _out(m.search_entries(args.query, category=args.category))
    m.close()


def cmd_mem_paper(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    p = m.get_paper(args.arxiv_id)
    _out(p if p else {"not_found": args.arxiv_id})
    m.close()


def cmd_mem_date(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    _out(m.get_papers_by_date(args.date))
    m.close()


def cmd_mem_record_paper(args: argparse.Namespace, cfg: Config) -> None:
    data = json.loads(args.json_data)
    aid = data.pop("arxiv_id", None)
    if not aid:
        _err("json must include arxiv_id")
    title = data.pop("title", "")
    if not title:
        _err("json must include title")
    m = _mem(cfg)
    m.record_paper(
        aid,
        title,
        authors=data.get("authors"),
        report_date=data.get("report_date", ""),
        tags=data.get("tags"),
        novelty=data.get("novelty"),
        confidence=data.get("confidence"),
        paper_type=data.get("paper_type", ""),
        skip_reason=data.get("skip_reason", ""),
        included=bool(data.get("included", False)),
        issue_no=data.get("issue_no"),
        summary=data.get("summary", ""),
    )
    _out({"ok": True, "arxiv_id": aid})
    m.close()


def cmd_mem_link_topic(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    m.link_paper_topic(args.arxiv_id, args.topic)
    _out({"ok": True, "arxiv_id": args.arxiv_id, "topic": args.topic})
    m.close()


def cmd_mem_record_entry(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    m.record_entry(args.key, args.value, args.category)
    _out({"ok": True, "key": args.key, "category": args.category})
    m.close()


def cmd_mem_stats(args: argparse.Namespace, cfg: Config) -> None:
    m = _mem(cfg)
    _out(m.stats())
    m.close()


# ═══════════════════════════════════════════════════════════════
#  Argument parsing
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tcs-daily",
        description="Tool interface for tcs-daily. All output is JSON.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── data tools ─────────────────────────────────────────────
    p = sub.add_parser("fetch", help="Fetch candidates + arXiv metadata")
    p.add_argument("date", nargs="?", default=date_type.today().isoformat())

    p = sub.add_parser("metadata", help="arXiv metadata for one paper")
    p.add_argument("arxiv_id")

    p = sub.add_parser("download", help="Download PDF")
    p.add_argument("arxiv_id")
    p.add_argument("--url", default="")

    p = sub.add_parser("extract", help="Extract PDF text sections")
    p.add_argument("arxiv_id")

    p = sub.add_parser("history", help="Search past reports")
    p.add_argument("query")

    sub.add_parser("tags", help="List canonical report tags")

    # ── manifest ───────────────────────────────────────────────
    p = sub.add_parser("manifest", help="Update posts/manifest.json")
    p.add_argument("date")
    p.add_argument("path", help="e.g. posts/2026-03-04.md")
    p.add_argument("paper_count", type=int)

    # ── validate ───────────────────────────────────────────────
    p = sub.add_parser("validate", help="Check outputs")
    p.add_argument("date")

    # ── memory ─────────────────────────────────────────────────
    p_mem = sub.add_parser("memory", help="Knowledge base operations")
    msub = p_mem.add_subparsers(dest="mem_command")

    p = msub.add_parser("search", help="Search papers")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)

    p = msub.add_parser("topics", help="List/search topics")
    p.add_argument("query", nargs="?", default="")

    p = msub.add_parser("entries", help="Search knowledge entries")
    p.add_argument("query")
    p.add_argument("--category", default="")

    p = msub.add_parser("paper", help="Get one paper record")
    p.add_argument("arxiv_id")

    p = msub.add_parser("date", help="Get all papers from a date")
    p.add_argument("date")

    p = msub.add_parser("record-paper", help="Record/update a paper")
    p.add_argument("json_data", help='JSON string e.g. \'{"arxiv_id":"...","title":"..."}\'')

    p = msub.add_parser("link-topic", help="Link paper → topic")
    p.add_argument("arxiv_id")
    p.add_argument("topic")

    p = msub.add_parser("record-entry", help="Record a knowledge entry")
    p.add_argument("key")
    p.add_argument("value")
    p.add_argument("category", help="result | technique | concept | open_problem | definition")

    msub.add_parser("stats", help="Show knowledge base stats")

    # ── dispatch ───────────────────────────────────────────────
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        raise SystemExit(0)

    cfg = Config.load()

    dispatch = {
        "fetch": cmd_fetch,
        "metadata": cmd_metadata,
        "download": cmd_download,
        "extract": cmd_extract,
        "history": cmd_history,
        "tags": cmd_tags,
        "manifest": cmd_manifest,
        "validate": cmd_validate,
    }
    if args.command in dispatch:
        dispatch[args.command](args, cfg)
        return

    if args.command == "memory":
        if not args.mem_command:
            p_mem.print_help()
            raise SystemExit(0)
        mem_dispatch = {
            "search": cmd_mem_search,
            "topics": cmd_mem_topics,
            "entries": cmd_mem_entries,
            "paper": cmd_mem_paper,
            "date": cmd_mem_date,
            "record-paper": cmd_mem_record_paper,
            "link-topic": cmd_mem_link_topic,
            "record-entry": cmd_mem_record_entry,
            "stats": cmd_mem_stats,
        }
        mem_dispatch[args.mem_command](args, cfg)
