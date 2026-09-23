from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from run_codex import (
    _base_arxiv_id,
    _is_weekend,
    _selected_draft_paths,
    codex,
    main,
    prompt_assembly,
    prompt_paper,
    prompt_screening,
)
from tcs_daily.cli import cmd_manifest, cmd_tags, cmd_validate
from tcs_daily.config import Config


DATE = "2026-08-10"
ARXIV_ID = "2608.00001v2"
SCORES = (
    "**结果置信度：8.0/10** — 已核对 Theorem 1，附录未逐步复算。\n\n"
    "**写作质量：8.5/10** — 四点图解释了归约，参数一段仍较密。"
)


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

    @patch("run_codex.subprocess.run")
    def test_codex_uses_current_automatic_approval_flag(self, run) -> None:
        run.return_value.returncode = 0

        self.assertEqual(codex("prompt"), 0)

        command = run.call_args.args[0]
        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("--full-auto", command)
        self.assertIn("--ephemeral", command)
        self.assertIn('model_provider="chatgpt-http"', command)
        provider = next(arg for arg in command if arg.startswith("model_providers."))
        self.assertIn("supports_websockets = false", provider)
        self.assertIn("plugins", command)
        self.assertIn("apps", command)
        self.assertIn("remote_plugin", command)

    @patch("run_codex.subprocess.run")
    def test_codex_manual_mode_omits_automatic_approval(self, run) -> None:
        run.return_value.returncode = 0

        self.assertEqual(codex("prompt", full_auto=False), 0)

        command = run.call_args.args[0]
        self.assertNotIn("--approve-for-me", command)
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)

    def test_screening_prompt_forbids_expensive_network_work(self) -> None:
        prompt = prompt_screening(DATE)

        self.assertIn("不要下载或提取 PDF", prompt)
        self.assertIn("不要发起网页搜索", prompt)

    def test_writing_prompts_use_only_prepared_local_inputs(self) -> None:
        paper_prompt = prompt_paper(
            DATE,
            {"arxiv_id": ARXIV_ID, "title": "Example", "tags": ["exact-algorithms"]},
            "memory",
        )
        assembly_prompt = prompt_assembly(
            DATE,
            [f"data/cache/drafts/{DATE}/{ARXIV_ID}.md"],
            f"data/cache/selection/{DATE}.json",
        )

        self.assertIn("不要调用 `fetch`、`metadata` 或 `download`", paper_prompt)
        self.assertIn("不要发起网页搜索", paper_prompt)
        self.assertIn("不要发起网页搜索", assembly_prompt)


class TaggingPolicyTests(unittest.TestCase):
    def test_tags_command_exposes_assignment_policy(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_tags(Namespace(), Config.load(Path(".")))
        payload = json.loads(output.getvalue())
        policy = payload["tagging_policy"]
        self.assertIn("main theorem", policy["primary_rule"])
        self.assertGreaterEqual(len(policy["common_confusions"]), 4)


class PipelineExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        selection = self.root / "data/cache/selection" / f"{DATE}.json"
        draft = self.root / "data/cache/drafts" / DATE / f"{ARXIV_ID}.md"
        self.report = self.root / "posts" / f"{DATE}.md"
        for path in (selection, draft, self.report):
            path.parent.mkdir(parents=True, exist_ok=True)
        selection.write_text(json.dumps({"selected": [{"arxiv_id": ARXIV_ID}]}))
        draft.write_text("Draft content.\n" * 150)
        self.report.write_text("Report content.\n" * 150)
        for path in (selection, draft):
            os.utime(path, (100, 100))
        os.utime(self.report, (200, 200))

    def run_assembly(self, validation_results: list[dict]):
        with (
            patch("run_codex.ROOT", self.root),
            patch("sys.argv", ["run_codex.py", "--date", DATE, "--stage", "3"]),
            patch("run_codex.tool", side_effect=validation_results) as tool,
            patch("run_codex.codex", return_value=0) as agent,
        ):
            main()
        return tool, agent

    def test_reuses_validated_report_without_second_validation_or_agent(self) -> None:
        tool, agent = self.run_assembly([{"ok": True}])
        agent.assert_not_called()
        tool.assert_called_once_with(
            "validate", DATE, "--selection",
            f"data/cache/selection/{DATE}.json", "--require-scores",
        )

    def test_new_assembly_runs_only_final_validation(self) -> None:
        self.report.unlink()
        tool, agent = self.run_assembly([{"ok": True}])
        agent.assert_called_once()
        self.assertEqual(tool.call_count, 1)
        self.assertIn("--require-scores", tool.call_args.args)

    def test_invalid_cached_report_is_repaired_and_revalidated(self) -> None:
        tool, agent = self.run_assembly([
            {"ok": False, "errors": ["Missing scores"]}, {"ok": True},
        ])
        agent.assert_called_once()
        self.assertEqual(tool.call_count, 2)


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
        body: str = "Analysis.",
    ) -> None:
        close = "\n::::\n" if close_issue else "\n"
        self.report_path.write_text(
            "---\n"
            f"date: {DATE}\n"
            "---\n\n"
            "::::issue[exact-algorithms]\n"
            f"## Example Paper [arXiv:{ARXIV_ID}]"
            f"(https://arxiv.org/abs/{link_target})\n\n"
            f"{body}"
            f"{close}",
            "utf-8",
        )

    def rebuild_manifest(self) -> None:
        with redirect_stdout(io.StringIO()):
            cmd_manifest(
                Namespace(date=DATE, path=f"posts/{DATE}.md", paper_count=1),
                self.cfg,
            )

    def validate(self, *, selection: str = "", require_scores: bool = False) -> tuple[int, dict]:
        output = io.StringIO()
        code = 0
        try:
            with redirect_stdout(output):
                cmd_validate(
                    Namespace(date=DATE, selection=selection, require_scores=require_scores),
                    self.cfg,
                )
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

    def test_score_validation_is_opt_in_for_legacy_reports(self) -> None:
        self.assertEqual(self.validate()[0], 0)
        code, payload = self.validate(require_scores=True)
        self.assertEqual(code, 1)
        self.assertIn("结果置信度", " ".join(payload["errors"]))
        self.assertIn("写作质量", " ".join(payload["errors"]))

    def test_accepts_decimal_scores_and_both_endpoints(self) -> None:
        for scores in (SCORES, SCORES.replace("8.0/10", "0/10").replace("8.5/10", "10/10")):
            with self.subTest(scores=scores):
                self.write_report(body=f"Analysis.\n\n{scores}")
                code, payload = self.validate(require_scores=True)
                self.assertEqual((code, payload["errors"]), (0, []))

    def test_rejects_out_of_range_or_non_numeric_scores(self) -> None:
        for score in ("-1", "10.1", "10.000000000000000001", "NaN", "inf", "八", "8e0"):
            with self.subTest(score=score):
                self.write_report(body=SCORES.replace("8.0/10", f"{score}/10"))
                self.assertEqual(self.validate(require_scores=True)[0], 1)

    def test_each_score_needs_a_reason(self) -> None:
        for paragraph in SCORES.split("\n\n"):
            with self.subTest(paragraph=paragraph):
                without_reason = paragraph.split(" — ")[0] + " —   "
                self.write_report(body=SCORES.replace(paragraph, without_reason))
                self.assertEqual(self.validate(require_scores=True)[0], 1)

    def test_required_scores_use_new_writing_quality_label(self) -> None:
        self.write_report(body=SCORES.replace("写作质量", "写作说人话程度"))
        code, payload = self.validate(require_scores=True)
        self.assertEqual(code, 1)
        self.assertIn("写作质量", " ".join(payload["errors"]))

    def test_scores_must_be_unique_and_at_the_end_of_each_issue(self) -> None:
        for body in (
            f"{SCORES}\n\nMore analysis after scores.",
            f"{SCORES}\n\n{SCORES}",
            f":::aside[评分]\n{SCORES}\n:::",
        ):
            with self.subTest(body=body):
                self.write_report(body=body)
                self.assertEqual(self.validate(require_scores=True)[0], 1)

    def test_scores_outside_issue_do_not_satisfy_requirement(self) -> None:
        with self.report_path.open("a") as report:
            report.write(f"\n{SCORES}\n")
        self.assertEqual(self.validate(require_scores=True)[0], 1)

    def test_every_issue_requires_its_own_scores(self) -> None:
        self.write_report(body=f"Analysis.\n\n{SCORES}")
        with self.report_path.open("a") as report:
            report.write(
                "\n::::issue[exact-algorithms]\n"
                "## Second paper [arXiv:2608.00002](https://arxiv.org/abs/2608.00002)\n\n"
                "Analysis without scores.\n::::\n"
            )
        self.rebuild_manifest()
        code, payload = self.validate(require_scores=True)
        self.assertEqual(code, 1)
        self.assertTrue(all(error.startswith("Issue 2:") for error in payload["errors"]))


if __name__ == "__main__":
    unittest.main()
