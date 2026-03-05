"""Fetch paper lists from theory.report and metadata from arXiv."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup, Tag

from . import _http
from .cache import read_json, write_json
from .config import Paths

# ── theory.report ──────────────────────────────────────────────

THEORY_REPORT_URL = "https://theory.report/"


def _date_labels(date: str) -> set[str]:
    dt = datetime.strptime(date, "%Y-%m-%d")
    return {
        dt.strftime(fmt)
        for fmt in (
            "%A, %B %d",
            "%A, %B %-d",
            "%a, %b %d",
            "%a, %b %-d",
            "%b %d, %Y",
            "%b %-d, %Y",
            "%B %d, %Y",
            "%B %-d, %Y",
            "%Y-%m-%d",
        )
    }


def _extract_arxiv_id(href: str) -> str:
    path = urlparse(href).path.rstrip("/")
    for prefix in ("/abs/", "/pdf/"):
        if path.startswith(prefix):
            return path.removeprefix(prefix).removesuffix(".pdf")
    return path.rsplit("/", 1)[-1].removesuffix(".pdf")


def _parse_entry(heading: Tag, date: str) -> dict | None:
    link = heading.find("a", href=True)
    if link is None or "arxiv.org" not in link["href"]:
        return None
    title = " ".join(link.get_text(" ", strip=True).split())
    arxiv_id = _extract_arxiv_id(link["href"])
    authors: list[str] = []
    source_hint = ""

    sib = heading.find_next_sibling()
    while sib and sib.name not in {"h2", "h3"}:
        if sib.name:
            text = " ".join(sib.get_text(" ", strip=True).split())
            if text.startswith("Authors:") and not authors:
                raw = text.removeprefix("Authors:").strip()
                if "," in raw:
                    authors = [a.strip() for a in raw.split(",") if a.strip()]
                elif " and " in raw:
                    authors = [a.strip() for a in raw.split(" and ") if a.strip()]
                elif raw:
                    authors = [raw]
            elif text.startswith("from ") and not source_hint:
                source_hint = text
        sib = sib.find_next_sibling()

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "date": date,
        "source_hint": source_hint,
    }


def fetch_theory_report(date: str, paths: Paths) -> list[dict]:
    """Fetch candidate papers from theory.report for *date*.

    Returns cached result if available.
    """
    cache = paths.theory_report_cache(date)
    if cache.exists():
        return read_json(cache)["entries"]

    html = _http.get_text(THEORY_REPORT_URL)
    soup = BeautifulSoup(html, "html.parser")
    labels = _date_labels(date)
    section = None
    headings_seen: list[str] = []

    for h2 in soup.find_all("h2"):
        text = " ".join(h2.get_text(" ", strip=True).split())
        headings_seen.append(text)
        if text in labels:
            section = h2
            break

    if section is None:
        raise RuntimeError(
            f"theory.report has no section for {date}.\n"
            f"Expected one of: {sorted(labels)}\n"
            f"Saw: {', '.join(headings_seen[:8])}"
        )

    entries: list[dict] = []
    seen: set[str] = set()
    for node in section.find_all_next():
        if not isinstance(node, Tag):
            continue
        if node.name == "h2":
            break
        if node.name != "h3":
            continue
        entry = _parse_entry(node, date)
        if entry and entry["arxiv_id"] not in seen:
            seen.add(entry["arxiv_id"])
            entries.append(entry)

    if not entries:
        raise RuntimeError(f"No arXiv entries found for {date} on theory.report.")

    write_json(cache, {"date": date, "count": len(entries), "entries": entries})
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
