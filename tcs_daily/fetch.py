"""Fetch candidate papers from arXiv recent listings and metadata from arXiv."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup, Tag

from . import _http
from .cache import read_json, write_json
from .config import Paths

ARXIV_RECENT_CATEGORIES = ("cs.CC", "cs.CG", "cs.DS")
ARXIV_RECENT_URL = "https://arxiv.org/list/{category}/recent"


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


def _extract_arxiv_id(href: str) -> str:
    path = urlparse(href).path.rstrip("/")
    for prefix in ("/abs/", "/pdf/"):
        if path.startswith(prefix):
            return path.removeprefix(prefix).removesuffix(".pdf")
    return path.rsplit("/", 1)[-1].removesuffix(".pdf")


def _heading_date(text: str) -> str | None:
    head = _normalize_space(text).split(" (", 1)[0]
    try:
        return datetime.strptime(head, "%a, %d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_recent_entry(dt: Tag, dd: Tag, *, date: str, category: str) -> dict | None:
    abs_link = next(
        (link for link in dt.find_all("a", href=True) if "/abs/" in link["href"]),
        None,
    )
    if abs_link is None:
        return None

    title_block = dd.find("div", class_="list-title")
    title = _normalize_space(title_block.get_text(" ", strip=True)) if title_block else ""
    title = title.removeprefix("Title:").strip()
    if not title:
        return None

    authors = [
        _normalize_space(link.get_text(" ", strip=True))
        for link in dd.select(".list-authors a")
    ]
    subjects_block = dd.find("div", class_="list-subjects")
    comments_block = dd.find("div", class_="list-comments")
    subjects = (
        _normalize_space(subjects_block.get_text(" ", strip=True)).removeprefix("Subjects:").strip()
        if subjects_block else ""
    )
    comments = (
        _normalize_space(comments_block.get_text(" ", strip=True)).removeprefix("Comments:").strip()
        if comments_block else ""
    )

    source_parts = [f"arXiv recent {category}"]
    if subjects:
        source_parts.append(f"Subjects: {subjects}")
    if comments:
        source_parts.append(f"Comments: {comments}")

    return {
        "arxiv_id": _extract_arxiv_id(abs_link["href"]),
        "title": title,
        "authors": authors,
        "date": date,
        "source_hint": " | ".join(source_parts),
        "listing_categories": [category],
    }


def _parse_recent_listing(html: str, *, date: str, category: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []

    for heading in soup.find_all("h3"):
        if _heading_date(heading.get_text(" ", strip=True)) != date:
            continue

        pending_dt: Tag | None = None
        node = heading.find_next_sibling()
        while node is not None:
            if not isinstance(node, Tag):
                node = node.find_next_sibling()
                continue
            if node.name == "h3":
                break
            if node.name == "dt":
                pending_dt = node
            elif node.name == "dd" and pending_dt is not None:
                entry = _parse_recent_entry(
                    pending_dt, node, date=date, category=category
                )
                if entry is not None:
                    entries.append(entry)
                pending_dt = None
            node = node.find_next_sibling()
        break

    return entries


def fetch_recent_arxiv(date: str, paths: Paths) -> list[dict]:
    """Fetch candidate papers from recent arXiv category pages for *date*."""
    cache = paths.candidates_cache(date)
    if cache.exists():
        return read_json(cache)["entries"]

    merged: dict[str, dict] = {}
    for category in ARXIV_RECENT_CATEGORIES:
        html = _http.get_text(ARXIV_RECENT_URL.format(category=category))
        for entry in _parse_recent_listing(html, date=date, category=category):
            existing = merged.get(entry["arxiv_id"])
            if existing is None:
                merged[entry["arxiv_id"]] = entry
                continue

            categories = existing.setdefault("listing_categories", [])
            for item in entry.get("listing_categories", []):
                if item not in categories:
                    categories.append(item)
            existing["source_hint"] = " | ".join(
                sorted(
                    {
                        part.strip()
                        for part in (
                            existing.get("source_hint", "").split("|")
                            + entry.get("source_hint", "").split("|")
                        )
                        if part.strip()
                    }
                )
            )

    entries = list(merged.values())
    if not entries:
        raise RuntimeError(
            f"No arXiv entries found for {date} in recent listings for "
            f"{', '.join(ARXIV_RECENT_CATEGORIES)}."
        )

    write_json(
        cache,
        {
            "date": date,
            "sources": list(ARXIV_RECENT_CATEGORIES),
            "count": len(entries),
            "entries": entries,
        },
    )
    return entries


# ── arXiv API ──────────────────────────────────────────────────

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def _atom_text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def fetch_arxiv_metadata(
    arxiv_id: str,
    paths: Paths,
    *,
    hint: dict | None = None,
) -> dict:
    """Fetch arXiv metadata for one paper. Returns cached result if available."""
    cache = paths.arxiv_cache(arxiv_id)
    if cache.exists():
        return read_json(cache)

    xml_text = _http.get_text(
        f"{ARXIV_API}?{urlencode({'id_list': arxiv_id})}"
    )
    root = ET.fromstring(xml_text)
    entry = root.find("a:entry", ATOM)
    if entry is None:
        raise RuntimeError(f"arXiv API returned no entry for {arxiv_id}")

    title = _atom_text(entry.find("a:title", ATOM))
    authors = [
        _atom_text(a.find("a:name", ATOM))
        for a in entry.findall("a:author", ATOM)
    ]
    authors = [a for a in authors if a]
    categories = [
        c.attrib["term"]
        for c in entry.findall("a:category", ATOM)
        if "term" in c.attrib
    ]

    pdf_url = ""
    for link in entry.findall("a:link", ATOM):
        if (
            link.attrib.get("title") == "pdf"
            or link.attrib.get("type") == "application/pdf"
        ):
            pdf_url = link.attrib.get("href", "")
    if not pdf_url:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    hint = hint or {}
    meta = {
        "arxiv_id": arxiv_id,
        "title": title or hint.get("title", ""),
        "authors": authors or hint.get("authors", []),
        "abstract": _atom_text(entry.find("a:summary", ATOM)),
        "categories": categories,
        "pdf_url": pdf_url,
        "source_url": f"https://arxiv.org/abs/{arxiv_id}",
        "published_at": _atom_text(entry.find("a:published", ATOM)),
    }
    write_json(cache, meta)
    return meta
