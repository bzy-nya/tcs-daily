"""PDF download and text extraction."""

from __future__ import annotations

import re
import subprocess
import os
import json
from pathlib import Path

from . import _http
from .cache import read_json, write_json
from .config import Paths


# ── download ───────────────────────────────────────────────────


def download(arxiv_id: str, pdf_url: str, paths: Paths) -> Path:
    """Download a PDF.  Skips if the file already exists (>1 KB)."""
    dest = paths.pdf_file(arxiv_id)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_http.get(pdf_url, timeout=60))
    return dest


# ── text extraction backends ───────────────────────────────────


def _pymupdf(path: Path) -> str:
    """Extract text via PyMuPDF (fitz) — best quality for academic PDFs."""
    try:
        import fitz  # type: ignore[import-untyped]

        doc = fitz.open(str(path))
        pages: list[str] = []
        for page in doc:
            pages.append(page.get_text("text"))
        doc.close()
        return "\n\n".join(pages)
    except Exception:
        return ""


def _textutil(path: Path) -> str:
    """macOS textutil PDF→text (fast, decent quality)."""
    try:
        r = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, text=True,
        )
        return r.stdout if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _pdfkit(path: Path) -> str:
    """macOS PDFKit via Swift — robust fallback when textutil fails."""
    if not Path("/usr/bin/swift").exists():
        return ""
    module_cache = Path("/tmp/tcs-daily-swift-module-cache")
    module_cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Sandbox-safe cache/home overrides; avoids writes to ~/.cache/clang.
    env["SWIFT_MODULECACHE_PATH"] = str(module_cache)
    env["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    env["XDG_CACHE_HOME"] = "/tmp"
    env["HOME"] = "/tmp"
    path_literal = json.dumps(str(path))
    script = f"""
import Foundation
import PDFKit

let url = URL(fileURLWithPath: {path_literal})
guard let doc = PDFDocument(url: url), let text = doc.string else {{
    exit(1)
}}
print(text)
"""
    try:
        r = subprocess.run(
            ["/usr/bin/swift", "-module-cache-path", str(module_cache), "-e", script],
            capture_output=True,
            text=True,
            env=env,
        )
        return r.stdout if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _strings(path: Path) -> str:
    """Last resort: extract printable strings from the PDF binary."""
    try:
        r = subprocess.run(
            ["/usr/bin/strings", "-n", "8", str(path)],
            capture_output=True, text=True,
        )
        return r.stdout if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""


# ── section splitting ──────────────────────────────────────────


def _normalize(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Patterns that match common academic section headings
_HEADING_RE = re.compile(
    r"^(?:(?:\d+\.?\s+)|(?:[IVXivx]+\.?\s+))?(.+)$"
)


def _canon(line: str) -> str:
    """Canonicalize a line for heading matching."""
    line = line.strip()
    m = _HEADING_RE.match(line)
    if m:
        line = m.group(1)
    return re.sub(r"\s+", " ", line).strip().lower()


def _find_heading(lines: list[str], names: tuple[str, ...]) -> int | None:
    for i, line in enumerate(lines):
        c = _canon(line)
        for n in names:
            if c == n or c.startswith(n + " ") or c.startswith(n + ":"):
                return i
    return None


def _slice(
    lines: list[str],
    starts: tuple[str, ...],
    ends: tuple[str, ...],
    max_chars: int = 12000,
) -> str:
    si = _find_heading(lines, starts)
    if si is None:
        return ""
    ei = len(lines)
    for name in ends:
        idx = _find_heading(lines[si + 1 :], (name,))
        if idx is not None:
            ei = min(ei, si + 1 + idx)
    text = "\n".join(l for l in lines[si + 1 : ei] if l.strip()).strip()
    return text[:max_chars]


# ── public API ─────────────────────────────────────────────────


def extract(arxiv_id: str, paths: Paths) -> dict:
    """Extract sections from a downloaded PDF.

    Tries PyMuPDF first (best for academic layout), then textutil,
    then /usr/bin/strings as last resort.  Returns cached result if
    available.
    """
    cache_path = paths.parsed_file(arxiv_id)
    if cache_path.exists():
        cached = read_json(cache_path)
        sections = cached.get("sections", {}) if isinstance(cached, dict) else {}
        abstract = sections.get("abstract", "") if isinstance(sections, dict) else ""
        full_text = sections.get("full_text", "") if isinstance(sections, dict) else ""
        # Recover from previously cached binary/garbled extraction.
        if not (
            isinstance(abstract, str)
            and isinstance(full_text, str)
            and (
                abstract.lstrip().startswith("%PDF-")
                or full_text.lstrip().startswith("%PDF-")
            )
        ):
            return cached

    pdf = paths.pdf_file(arxiv_id)
    if not pdf.exists():
        raise RuntimeError(f"PDF not found: {pdf}")

    # Try extractors in order of quality
    raw = _pymupdf(pdf) or _textutil(pdf) or _pdfkit(pdf) or _strings(pdf)
    if not raw.strip():
        raise RuntimeError(f"Could not extract text from {pdf}")

    text = _normalize(raw)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    abstract = _slice(
        lines,
        ("abstract",),
        ("introduction", "keywords", "1 introduction"),
    )
    if not abstract:
        # Many papers don't have an explicit "Abstract" heading —
        # grab the first ~2000 chars as a best effort.
        abstract = "\n".join(lines[:30])[:2000]

    intro = _slice(
        lines,
        ("introduction",),
        (
            "related work",
            "preliminaries",
            "background",
            "our results",
            "our contributions",
            "results",
            "main results",
            "model",
            "setup",
            "technical overview",
            "proof overview",
            "conclusion",
            "references",
        ),
    )
    if not intro:
        intro = "\n".join(lines[30:80])[:4000]

    results = _slice(
        lines,
        ("main results", "our results", "our contributions", "results", "contributions"),
        (
            "preliminaries",
            "proof overview",
            "proof sketch",
            "technical overview",
            "algorithm",
            "lower bound",
            "upper bound",
            "conclusion",
            "references",
        ),
    )

    techniques = _slice(
        lines,
        ("technical overview", "proof overview", "proof sketch", "our techniques"),
        (
            "preliminaries",
            "definitions",
            "conclusion",
            "references",
        ),
    )

    conclusion = _slice(
        lines,
        ("conclusion", "conclusions", "discussion", "concluding remarks"),
        ("references", "acknowledgments", "acknowledgements", "appendix"),
    )
    if not conclusion:
        conclusion = "\n".join(lines[-40:])[:3000]

    sections = {
        "abstract": abstract,
        "introduction": intro,
        "main_results": results,
        "techniques": techniques,
        "conclusion": conclusion,
        "full_text": text[:80000],
    }
    payload = {"arxiv_id": arxiv_id, "sections": sections}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, payload)
    return payload
