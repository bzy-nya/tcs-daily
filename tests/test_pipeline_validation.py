from __future__ import annotations

import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from run_codex import _base_arxiv_id, _is_weekend, _selected_draft_paths
from tcs_daily.cli import cmd_manifest, cmd_tags, cmd_validate
from tcs_daily.config import Config


DATE = "2026-08-10"
ARXIV_ID = "2608.00001v2"


class PipelineHelperTests(unittest.TestCase):
    def test_base_arxiv_id_removes_only_version_suffix(self) -> None:
        self.assertEqual(_base_arxiv_id(ARXIV_ID), "2608.00001")
        self.assertEqual(_base_arxiv_id("2608.00001"), "2608.00001")
        self.assertEqual(_base_arxiv_id("quant-ph/0505188v12"), "quant-ph/0505188")

    def test_selected_drafts_preserve_order_and_reject_duplicates(self) -> None:
        drafts = Path("drafts")
        selected = [{"arxiv_id": "2608.00002"}, {"arxiv_id": "2608.00001v2"}]
        self.assertEqual(
            _selected_draft_paths(selected, drafts),
            [drafts / "2608.00002.md", drafts / "2608.00001v2.md"],
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            _selected_draft_paths([selected[0], selected[0]], drafts)

    def test_weekend_detection(self) -> None:
        self.assertTrue(_is_weekend("2026-08-08"))
        self.assertTrue(_is_weekend("2026-08-09"))
        self.assertFalse(_is_weekend("2026-08-10"))


class TaggingPolicyTests(unittest.TestCase):
    def test_tags_command_exposes_assignment_policy(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_tags(Namespace(), Config.load(Path(".")))
        payload = json.loads(output.getvalue())
        policy = payload["tagging_policy"]
        self.assertIn("main theorem", policy["primary_rule"])
        self.assertGreaterEqual(len(policy["common_confusions"]), 4)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "posts").mkdir()
        self.cfg = Config.load(self.root)
        self.report_path = self.root / "posts" / f"{DATE}.md"
        self.selection_path = self.root / "data" / "selection.json"
        self.selection_path.parent.mkdir(parents=True)
        self.write_report()
        self.rebuild_manifest()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_report(
        self,
        *,
        close_issue: bool = True,
        link_target: str = "2608.00001",
    ) -> None:
        close = "\n::::\n" if close_issue else "\n"
        self.report_path.write_text(
            "---\n"
            f"date: {DATE}\n"
            "---\n\n"
            "::::issue[exact-algorithms]\n"
            f"## Example Paper [arXiv:{ARXIV_ID}]"
            f"(https://arxiv.org/abs/{link_target})\n\n"
            "Analysis."
            f"{close}",
            "utf-8",
        )

    def rebuild_manifest(self) -> None:
        with redirect_stdout(io.StringIO()):
            cmd_manifest(
                Namespace(date=DATE, path=f"posts/{DATE}.md", paper_count=1),
                self.cfg,
            )

    def validate(self, *, selection: str = "") -> tuple[int, dict]:
        output = io.StringIO()
        code = 0
        try:
            with redirect_stdout(output):
                cmd_validate(Namespace(date=DATE, selection=selection), self.cfg)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, json.loads(output.getvalue())

    def write_selection(self, ids: list[str]) -> None:
        self.selection_path.write_text(
            json.dumps({"selected": [{"arxiv_id": arxiv_id} for arxiv_id in ids]}),
            "utf-8",
        )

    def test_valid_report_matches_manifest_and_selection(self) -> None:
        self.write_selection([ARXIV_ID])
        code, payload = self.validate(selection="data/selection.json")
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "errors": []})

    def test_selection_mismatch_fails(self) -> None:
        self.write_selection([ARXIV_ID, "2608.00002"])
        code, payload = self.validate(selection="data/selection.json")
        self.assertEqual(code, 1)
        self.assertIn("Selection does not match report papers", " ".join(payload["errors"]))

    def test_unbalanced_issue_block_fails(self) -> None:
        self.write_report(close_issue=False)
        code, payload = self.validate()
        self.assertEqual(code, 1)
        self.assertIn("unbalanced", " ".join(payload["errors"]))

    def test_arxiv_label_and_target_must_match(self) -> None:
        self.write_report(link_target="2608.99999")
        self.rebuild_manifest()
        code, payload = self.validate()
        self.assertEqual(code, 1)
        self.assertIn("does not match link target", " ".join(payload["errors"]))

    def test_manifest_count_must_match_issue_count(self) -> None:
        manifest_path = self.root / "posts" / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["reports"][0]["paper_count"] = 2
        manifest_path.write_text(json.dumps(manifest), "utf-8")
        code, payload = self.validate()
        self.assertEqual(code, 1)
        self.assertIn("paper_count", " ".join(payload["errors"]))


if __name__ == "__main__":
    unittest.main()
