from __future__ import annotations

import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tcs_daily.cli import cmd_fetch
from tcs_daily.config import Config, Paths
from tcs_daily.fetch import fetch_arxiv_metadata


DATE = "2026-08-11"
ARXIV_ID = "2608.08616"


def complete_metadata() -> dict:
    return {
        "arxiv_id": ARXIV_ID,
        "title": "A Counting Lovász Local Lemma",
        "authors": ["Example Author"],
        "abstract": "A complete abstract for screening.",
        "categories": ["cs.DS"],
        "pdf_url": f"https://arxiv.org/pdf/{ARXIV_ID}v1",
        "source_url": f"https://arxiv.org/abs/{ARXIV_ID}",
        "published_at": "2026-08-09T10:05:13Z",
    }


class MetadataCacheRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = Paths(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_complete_candidate_hint_rebuilds_missing_paper_cache(self) -> None:
        hint = {**complete_metadata(), "listing_categories": ["cs.DS"]}

        with patch("tcs_daily.fetch._http.get_text") as get_text:
            result = fetch_arxiv_metadata(ARXIV_ID, self.paths, hint=hint)

        get_text.assert_not_called()
        self.assertEqual(result["abstract"], hint["abstract"])
        cached = json.loads(self.paths.arxiv_cache(ARXIV_ID).read_text("utf-8"))
        self.assertEqual(cached, result)

    def test_incomplete_paper_cache_is_refreshed(self) -> None:
        cache = self.paths.arxiv_cache(ARXIV_ID)
        cache.parent.mkdir(parents=True)
        cache.write_text(
            json.dumps({"arxiv_id": ARXIV_ID, "title": "Incomplete", "abstract": ""}),
            "utf-8",
        )
        atom = f"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>A Counting Lovász Local Lemma</title>
            <summary>Recovered abstract.</summary>
            <published>2026-08-09T10:05:13Z</published>
            <author><name>Example Author</name></author>
            <category term="cs.DS" />
            <link title="pdf" type="application/pdf"
                  href="https://arxiv.org/pdf/2608.08616v1" />
          </entry>
        </feed>"""

        with patch("tcs_daily.fetch._http.get_text", return_value=atom):
            result = fetch_arxiv_metadata(ARXIV_ID, self.paths)

        self.assertEqual(result["abstract"], "Recovered abstract.")
        cached = json.loads(cache.read_text("utf-8"))
        self.assertEqual(cached["abstract"], "Recovered abstract.")


class CandidateCachePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cfg = Config.load(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fetch_persists_enriched_candidates_and_clears_old_error(self) -> None:
        listing = {
            "arxiv_id": ARXIV_ID,
            "title": "A Counting Lovász Local Lemma",
            "authors": ["Example Author"],
            "date": DATE,
            "listing_categories": ["cs.DS"],
            "metadata_error": "temporary failure",
        }

        output = io.StringIO()
        with (
            patch("tcs_daily.fetch.fetch_recent_arxiv", return_value=[listing]),
            patch("tcs_daily.fetch.fetch_arxiv_metadata", return_value=complete_metadata()),
            patch("tcs_daily.cli.time.sleep"),
            redirect_stdout(output),
        ):
            cmd_fetch(Namespace(date=DATE), self.cfg)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["papers"][0]["abstract"], "A complete abstract for screening.")
        self.assertNotIn("metadata_error", payload["papers"][0])

        cached = json.loads(
            self.cfg.paths.candidates_cache(DATE).read_text("utf-8")
        )
        self.assertEqual(cached["entries"], payload["papers"])
        self.assertEqual(cached["count"], 1)


if __name__ == "__main__":
    unittest.main()
