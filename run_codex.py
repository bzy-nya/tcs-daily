#!/usr/bin/env python3
"""Multi-stage pipeline: screening → per-paper analysis → assembly.

Stage 1  Codex screens candidates, picks 3-5 papers.
Stage 2  For each paper, a dedicated Codex call does deep analysis.
Stage 3  Codex assembles the final report from individual drafts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ── helpers ────────────────────────────────────────────────────


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _tool_error(stderr: str) -> str:
    text = stderr.strip()
    if not text:
        return "unknown error"
    try:
        payload = json.loads(text.splitlines()[-1])
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
    except json.JSONDecodeError:
        pass
    return text.splitlines()[-1]


def tool(*args: str) -> dict | list | None:
    """Run a tcs-daily CLI command, return parsed JSON or None."""
    r = subprocess.run(
        [sys.executable, "-m", "tcs_daily", *args],
        capture_output=True, text=True, cwd=ROOT,
    )
    if r.returncode != 0:
        _log(f"[tool] {' '.join(args)} failed: {_tool_error(r.stderr or r.stdout)}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _looks_complete(path: Path, *, min_size: int = 200) -> bool:
    return path.exists() and path.stat().st_size >= min_size


def _base_arxiv_id(arxiv_id: str) -> str:
    """Remove only a trailing arXiv version suffix such as ``v2``."""
    return re.sub(r"v\d+$", "", arxiv_id)


def _is_weekend(value: str) -> bool:
    """Return whether an ISO report date falls on Saturday or Sunday."""
    return date.fromisoformat(value).weekday() >= 5


def _selected_draft_paths(selected: list[dict], drafts_dir: Path) -> list[Path]:
    """Return draft paths in selection order, rejecting malformed selections."""
    paths: list[Path] = []
    seen: set[str] = set()
    for paper in selected:
        arxiv_id = paper.get("arxiv_id")
        if not isinstance(arxiv_id, str) or not arxiv_id.strip():
            raise ValueError("every selected paper must have a non-empty arxiv_id")
        if arxiv_id in seen:
            raise ValueError(f"duplicate selected arXiv id: {arxiv_id}")
        seen.add(arxiv_id)
        paths.append(drafts_dir / f"{arxiv_id}.md")
    if not paths:
        raise ValueError("selection contains no papers")
    return paths


def codex(prompt: str, *, model: str = "", full_auto: bool = True) -> int:
    """Run ``codex exec`` with *prompt* piped to stdin."""
    import os

    cmd = [
        "codex",
        "exec",
        "-C",
        str(ROOT),
        "--ephemeral",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--disable",
        "remote_plugin",
        "-c",
        'model_provider="chatgpt-http"',
        "-c",
        (
            'model_providers.chatgpt-http={ name = "ChatGPT HTTP", '
            'base_url = "https://chatgpt.com/backend-api/codex", '
            'wire_api = "responses", requires_openai_auth = true, '
            'supports_websockets = false }'
        ),
    ]
    if full_auto:
        cmd.append("--approve-for-me")
    else:
        cmd.extend(["--sandbox", "workspace-write"])
    if model:
        cmd.extend(["--model", model])
    cmd.append("-")

    # Ensure bin/tcs-daily is in PATH so codex sandbox can find it
    env = os.environ.copy()
    bin_dir = str(ROOT / "bin")
    env["PATH"] = bin_dir + ":" + env.get("PATH", "")

    return subprocess.run(cmd, input=prompt, text=True, cwd=ROOT, env=env).returncode


def memory_context_for(tags: list[str]) -> str:
    """Build a memory-context block by querying the knowledge base."""
    sections: list[str] = []
    seen_papers: set[str] = set()
    seen_entries: set[str] = set()

    for tag in tags[:6]:
        papers = tool("memory", "search", tag) or []
        for p in papers[:3]:
            aid = p["arxiv_id"]
            if aid in seen_papers:
                continue
            seen_papers.add(aid)
            line = f"- [{aid}] {p['title']}"
            if p.get("summary"):
                line += f"\n  {p['summary'][:300]}"
            sections.append(line)

        entries = tool("memory", "entries", tag) or []
        for e in entries[:3]:
            k = e["key"]
            if k in seen_entries:
                continue
            seen_entries.add(k)
            sections.append(f"- [{e['category']}] {k}: {e['value'][:300]}")

    if not sections:
        return "(知识库中暂无相关记录)"
    return "\n".join(sections)


# ── prompts ────────────────────────────────────────────────────


def prompt_screening(dt: str) -> str:
    return f"""\
Use the $tcs-daily skill，执行其中的筛选阶段。

为 {dt} 的日报筛选 2-5 篇最值得深入讲解的论文。
读取一次 `tcs-daily fetch {dt}` 的缓存摘要和 `tcs-daily tags`；
仅在需要已有研究脉络或选题偏好时定向查询知识库，不必先遍历 stats/topics。
不要下载或提取 PDF，不要发起网页搜索或其他外部网络请求。

优先考虑明确的新定理、算法或下界，权衡新颖性、重要性、陈述合理性与话题多样性。
按主定理所属的研究问题选最具体的 canonical tag，遵循 tags 返回的 tagging_policy。
默认每篇 1 个 tag，两个独立主要贡献才允许 2 个，不新建 tag。

写入 `data/cache/selection/{dt}.json`：
```json
{{
  "selected": [
    {{"arxiv_id": "...", "title": "...", "tags": ["..."], "reason": "一句话入选理由"}}
  ],
  "skipped_notable": [
    {{"arxiv_id": "...", "title": "...", "reason": "一句话跳过理由"}}
  ]
}}
```
`skipped_notable` 只列值得一提的论文，不穷举候选。此阶段不评全文置信度和写作分。
"""


def prompt_paper(dt: str, paper: dict, memory_ctx: str) -> str:
    aid = paper["arxiv_id"]
    title = paper.get("title", "")
    reason = paper.get("reason", "")
    tags = ", ".join(paper.get("tags", []))

    return f"""\
Use the $tcs-daily skill，执行其中的单篇分析阶段。

为 {dt} 的日报撰写一篇深度解读：
- arXiv: {aid}
- 标题: {title}
- 已选 tags: {tags}
- 入选理由: {reason}

## 已提供的知识库上下文
{memory_ctx}

读取一次 `tcs-daily extract {aid}`（已预提取），后续在本地结果中定位需要的段落。
返回字段为 abstract, introduction, main_results, techniques, conclusion, full_text；
section 为空时在 full_text 中搜索。严禁自己写 PDF 解析脚本或安装额外 PDF 工具。
已有知识库上下文直接复用，只有明确的信息缺口才追加定向查询。
不要调用 `fetch`、`metadata` 或 `download`，不要发起网页搜索或其他外部网络请求。
只使用预提取全文、论文自身参考文献、知识库和本地往期日报，不猜测参考文献链接。

遵循 skill 的“无背景读者协议”、写作规范和“两项评分”。
本上下文尚未读过风格标杆时，阅读一次 `posts/2026-03-05.md`。
把背景、精确定理、技术思路和具体判断写成连贯叙事，通常 3000-6000 字。
将完整 `::::issue[...]` 论文块写入 `data/cache/drafts/{dt}/{aid}.md`，
两项显式评分及各自依据放在该篇正文末尾、关闭 `::::` 之前。

完成一次合并复核：核对主结果和关键证明依据，并冷读正文检查概念、例子及可读性。
已有核查结论直接用于评分；不要为打分再重读一遍全文。修正后只复查受影响段落。
将已核对的定理/引理位置、关键假设、未解决疑点和两项评分依据写入论文记忆的 summary，
用 `tcs-daily memory record-paper` 记录 arxiv_id、title、tags、summary、included=true、report_date。
按需 link-topic / record-entry，只保存值得跨天复用的信息，不重复写入未变化条目。
"""


def prompt_assembly(dt: str, draft_files: list[str], selection_rel: str) -> str:
    listing = "\n".join(f"- `{f}`" for f in draft_files)
    n = len(draft_files)

    return f"""\
Use the $tcs-daily skill，执行其中的总装阶段。

为 {dt} 组装日报，读取一次 `{selection_rel}` 及以下 {n} 篇稿件：
{listing}

复用单篇分析已经完成的事实核查、tags 和评分，仅做跨篇一致性与实际改动的检查。
不要重新列前置概念、逐篇做完整冷读、重复查知识库或通读原论文。
组装阶段只处理本地文件，不要发起网页搜索或其他外部网络请求。
仅遇到具体矛盾、缺项或旧稿缺评分时，按 skill 的补查规则处理对应论文。

写入 `posts/{dt}.md`：
- YAML frontmatter：date: {dt}。
- 块外 `## 编辑按语`：不超过 300 字，概述入选方向；有真实联系才谈共同主题。
- 每篇一个 `::::issue[tags]` 块，块内 `## 论文标题 [arXiv:ID](https://arxiv.org/abs/ID)`。
  已有论文块直接保留，旧稿没有时再包裹，避免嵌套 issue。
  保留深度、核心解释、running example、数学公式和两项末尾评分及依据。
  每篇需独立可读；不同论文必要的相同概念解释可以保留。
- 块后 `## 未入选但值得关注`：按 selection 的 skipped_notable 每篇写 1-2 句话；无内容可省略。

只修正具体问题：跨篇术语冲突、明显重复套话、格式错误或缺失解释。
不要为统一结构压缩背景、改写全部正文或强制每篇用不同的结尾。
数学只用 `$...$` / `$$...$$`，不能改成反引号或代码块；往期日报链接用 `#YYYY-MM-DD`。
评分依据改变时才更新对应评分，不为统一分数分布重新打分。

最后运行一次 `tcs-daily manifest {dt} posts/{dt}.md {n}`。
不要在本阶段运行 validate；主程序负责唯一一次最终结构与评分验证。
"""


# ── main ───────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-stage TCS daily pipeline via codex exec.")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--model", default="")
    ap.add_argument(
        "--allow-weekend",
        action="store_true",
        help="Allow an explicit Saturday/Sunday run (disabled by default)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print prompts without running Codex")
    ap.add_argument("--no-full-auto", action="store_true")
    ap.add_argument("--stage", type=int, choices=[1, 2, 3],
                    help="Run only this stage (assumes prior stages done)")
    ap.add_argument(
        "--force-stage",
        type=int,
        choices=[1, 2, 3],
        action="append",
        default=[],
        help="Rerun a stage even if its cached outputs already exist",
    )
    args = ap.parse_args()

    dt = args.date
    try:
        weekend = _is_weekend(dt)
    except ValueError as exc:
        ap.error(f"--date must be an ISO date (YYYY-MM-DD): {exc}")
    if weekend and not args.allow_weekend:
        _log(f"[skip] {dt} is a weekend; arXiv does not publish a daily update")
        _log("[skip] use --allow-weekend only for an intentional manual backfill")
        return

    fa = not args.no_full_auto
    model = args.model
    run_stage = args.stage  # None = all
    force_stages = set(args.force_stage)
    requested_stages = [run_stage] if run_stage else [1, 2, 3]

    sel_path = ROOT / "data" / "cache" / "selection" / f"{dt}.json"
    drafts_dir = ROOT / "data" / "cache" / "drafts" / dt
    report_path = ROOT / "posts" / f"{dt}.md"

    mode = "dry-run" if args.dry_run else ("manual" if args.no_full_auto else "full-auto")
    _log(f"[run] date={dt} stages={','.join(str(s) for s in requested_stages)} mode={mode}")

    # ════════════════════════════════════════════════════════════
    #  Stage 1 — screening
    # ════════════════════════════════════════════════════════════
    if run_stage in (None, 1):
        needs_screening = (
            args.dry_run
            or 1 in force_stages
            or not _looks_complete(sel_path)
        )
        if not needs_screening:
            _log("[stage 1] reusing cached selection")
        else:
            if not args.dry_run:
                _log(f"[stage 1] fetching candidates for {dt}")
                cand = tool("fetch", dt)
                if not cand:
                    raise SystemExit(1)
                _log(f"[stage 1] screening {cand['count']} candidates")
            else:
                _log("[stage 1] dry-run prompt")
            p1 = prompt_screening(dt)

            if args.dry_run:
                print(f"{'='*60}\nStage 1 prompt\n{'='*60}\n{p1}")
            else:
                sel_path.parent.mkdir(parents=True, exist_ok=True)
                rc = codex(p1, model=model, full_auto=fa)
                if rc != 0:
                    _log("[stage 1] codex failed")
                    raise SystemExit(rc)

    # ── read selection ─────────────────────────────────────────
    if not args.dry_run:
        if not sel_path.exists():
            _log(f"[error] {sel_path} not found — did stage 1 run?")
            raise SystemExit(1)
        selection = json.loads(sel_path.read_text())
        selected = selection.get("selected", [])
        try:
            selected_drafts = _selected_draft_paths(selected, drafts_dir)
        except ValueError as exc:
            _log(f"[selection] invalid: {exc}")
            raise SystemExit(1) from exc
        selected_ids = ", ".join(p["arxiv_id"] for p in selected) if selected else "(none)"
        _log(f"[selection] {len(selected)} papers: {selected_ids}")
    else:
        selected = [{"arxiv_id": "XXXX.XXXXXv1", "title": "(example)", "tags": ["exact-algorithms"], "reason": "…"}]
        selected_drafts = [drafts_dir / "XXXX.XXXXXv1.md"]

    if run_stage == 1:
        _log("[done] stage 1 complete")
        return

    # ════════════════════════════════════════════════════════════
    #  Stage 2 — per-paper deep analysis
    # ════════════════════════════════════════════════════════════
    if run_stage in (None, 2):
        drafts_dir.mkdir(parents=True, exist_ok=True)
        pending = []
        reused_drafts = 0
        for p in selected:
            draft_path = drafts_dir / f"{p['arxiv_id']}.md"
            if not args.dry_run and 2 not in force_stages and _looks_complete(draft_path, min_size=1200):
                reused_drafts += 1
                continue
            pending.append(p)
        _log(
            f"[stage 2] selected={len(selected)} cached={reused_drafts} pending={len(pending)}"
        )

        # pre-download + pre-extract all selected papers
        if not args.dry_run and pending:
            _log("[stage 2] preparing PDFs")
            failed: list[str] = []
            for i, p in enumerate(pending, 1):
                aid = p["arxiv_id"]
                _log(f"[stage 2 prep {i}/{len(pending)}] {aid}")
                dl = tool("download", aid)
                if dl is None:
                    failed.append(aid)
                    continue
                ex = tool("extract", aid)
                if ex is None:
                    failed.append(aid)
                    continue
                time.sleep(0.3)
            if failed:
                _log(
                    f"[stage 2] unavailable after prep: {', '.join(failed)}"
                )
                _log("[stage 2] aborting to avoid assembling an incomplete selection")
                raise SystemExit(1)
            _log(f"[stage 2] ready for drafting: {len(pending)}")

        drafting_failures: list[str] = []
        for i, paper in enumerate(pending, 1):
            aid = paper["arxiv_id"]
            tags = paper.get("tags", [])
            _log(f"[stage 2 write {i}/{len(pending)}] {aid}")

            mem_ctx = "(dry-run)" if args.dry_run else memory_context_for(tags)
            p2 = prompt_paper(dt, paper, mem_ctx)

            if args.dry_run:
                print(f"{'='*60}\nStage 2 prompt (paper {i})\n{'='*60}\n{p2}")
            else:
                rc = codex(p2, model=model, full_auto=fa)
                if rc != 0:
                    _log(f"[stage 2] codex failed for {aid}")
                    drafting_failures.append(aid)
                    continue
                draft_path = drafts_dir / f"{aid}.md"
                if not _looks_complete(draft_path, min_size=1200):
                    _log(f"[stage 2] missing or incomplete draft for {aid}")
                    drafting_failures.append(aid)

        if drafting_failures:
            _log(
                "[stage 2] aborting after draft failures: "
                + ", ".join(drafting_failures)
            )
            raise SystemExit(1)

    if run_stage == 2:
        _log("[done] stage 2 complete")
        return

    # ════════════════════════════════════════════════════════════
    #  Stage 3 — assembly
    # ════════════════════════════════════════════════════════════
    if run_stage in (None, 3):
        can_reuse_report = (
            not args.dry_run
            and 3 not in force_stages
            and 2 not in force_stages
            and _looks_complete(report_path, min_size=2000)
            and all(_looks_complete(path, min_size=1200) for path in selected_drafts)
            and report_path.stat().st_mtime
                >= max(sel_path.stat().st_mtime, *(path.stat().st_mtime for path in selected_drafts))
        )
        if can_reuse_report:
            cached_validation = tool(
                "validate", dt, "--selection", str(sel_path.relative_to(ROOT))
            )
            can_reuse_report = bool(cached_validation and cached_validation.get("ok"))

        if can_reuse_report:
            _log("[stage 3] reusing existing validated report")
        else:
            _log("[stage 3] assembling report")

            if not args.dry_run:
                missing_drafts = [
                    path for path in selected_drafts
                    if not _looks_complete(path, min_size=1200)
                ]
                if missing_drafts:
                    for path in missing_drafts:
                        _log(f"[stage 3] missing selected draft: {path.relative_to(ROOT)}")
                    raise SystemExit(1)
                draft_rels = [str(path.relative_to(ROOT)) for path in selected_drafts]
                _log(f"[stage 3] drafts={len(draft_rels)}")
            else:
                draft_rels = [f"data/cache/drafts/{dt}/XXXX.XXXXXv1.md"]

            sel_rel = str(sel_path.relative_to(ROOT))
            p3 = prompt_assembly(dt, draft_rels, sel_rel)

            if args.dry_run:
                print(f"{'='*60}\nStage 3 prompt\n{'='*60}\n{p3}")
                return
            else:
                rc = codex(p3, model=model, full_auto=fa)
                if rc != 0:
                    _log("[stage 3] codex failed")
                    raise SystemExit(rc)

    # ── post-flight ────────────────────────────────────────────
    result = tool("validate", dt, "--selection", str(sel_path.relative_to(ROOT)))
    if result and result.get("ok"):
        _log("[done] outputs validated")
    else:
        errs = result.get("errors", []) if result else ["validation failed"]
        _log(f"[done] validation issues: {errs}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
