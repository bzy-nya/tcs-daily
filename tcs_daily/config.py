"""Path layout configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _find_root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    root: Path

    # ── directories ────────────────────────────────────────────

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def cache(self) -> Path:
        return self.data / "cache"

    @property
    def pdf(self) -> Path:
        return self.data / "pdf"

    @property
    def parsed(self) -> Path:
        return self.data / "parsed"

    @property
    def posts(self) -> Path:
        return self.root / "posts"

    @property
    def references(self) -> Path:
        return self.root / "references"

    # ── per-date / per-paper cache paths ───────────────────────

    def theory_report_cache(self, date: str) -> Path:
        return self.cache / "theory-report" / f"{date}.json"

    def arxiv_cache(self, arxiv_id: str) -> Path:
        return self.cache / "arxiv" / f"{arxiv_id}.json"

    def selected_papers_cache(self, date: str) -> Path:
        return self.cache / "selected-papers" / f"{date}.json"

    def draft_cache(self, date: str, arxiv_id: str) -> Path:
        return self.cache / "drafts" / date / f"{arxiv_id}.json"

    def pdf_file(self, arxiv_id: str) -> Path:
        return self.pdf / f"{arxiv_id}.pdf"

    def parsed_file(self, arxiv_id: str) -> Path:
        return self.parsed / f"{arxiv_id}.json"

    def report_file(self, date: str) -> Path:
        return self.posts / f"{date}.md"

    def candidates_cache(self, date: str) -> Path:
        return self.cache / "candidates" / f"{date}.json"

    def manifest_file(self) -> Path:
        return self.posts / "manifest.json"

    @property
    def memory_db(self) -> Path:
        return self.root / "memory.db"


@dataclass
class Config:
    paths: Paths

    @classmethod
    def load(cls, root: Path | None = None) -> Config:
        root = root or _find_root()
        return cls(paths=Paths(root=root))
