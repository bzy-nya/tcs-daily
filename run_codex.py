#!/usr/bin/env python3
"""Multi-stage pipeline: screening → per-paper analysis → assembly.

Stage 1  Codex screens candidates, picks 3-5 papers.
Stage 2  For each paper, a dedicated Codex call does deep analysis.
Stage 3  Codex assembles the final report from individual drafts.
"""

from __future__ import annotations

import argparse
import json
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
        _log(f"[tool] {' '.join(args)} failed: {_tool_error(r.stderr)}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _looks_complete(path: Path, *, min_size: int = 200) -> bool:
    return path.exists() and path.stat().st_size >= min_size


def codex(prompt: str, *, model: str = "", full_auto: bool = True) -> int:
    """Run ``codex exec`` with *prompt* piped to stdin."""
    import os

    cmd = ["codex", "exec", "-C", str(ROOT), "--sandbox", "workspace-write"]
    if full_auto:
        cmd.append("--full-auto")
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
Use the $tcs-daily skill.

今天是 {dt}。请为日报筛选论文。

1. `tcs-daily fetch {dt}` 查看候选列表（来自 `cs.CC` / `cs.CG` / `cs.DS` 的 arXiv recent 页面，已缓存）。
2. `tcs-daily memory stats` 和 `tcs-daily memory topics` 回顾知识库积累。
3. 浏览每篇论文的摘要，选出 2-5 篇**最值得深入讲解**的论文。

选择标准（你自己把握权重）：
- 有明确新定理/算法/下界的原创研究
- 结果的新颖性与重要性
- 作者可信度、陈述合理性
- 知识库中积累的品味和偏好
- 话题多样性——尽量覆盖不同子方向，除非某方向今天集中出现重大进展

将结果写入 `data/cache/selection/{dt}.json`，格式：
```json
{{
  "selected": [
    {{"arxiv_id": "...", "title": "...", "tags": ["..."], "reason": "一句话为什么选"}}
  ],
  "skipped_notable": [
    {{"arxiv_id": "...", "title": "...", "reason": "一句话为什么跳过"}}
  ]
}}
```
`skipped_notable` 只列值得一提但未入选的，不需要穷举所有候选。

**关于 tags**：
1. 先运行 `tcs-daily tags`，它给出**唯一允许使用**的标签集合。
2. 每篇只打 **1 个** tag；只有论文确实横跨两个独立子方向时才允许 **2 个**。
3. 只能从 `tcs-daily tags` 返回的 tag key 中选择；**不要**新建 tag。
4. **不要**用 `algorithms` `complexity` `graph-theory` 这种一级大类。
"""


def prompt_paper(dt: str, paper: dict, memory_ctx: str) -> str:
    aid = paper["arxiv_id"]
    title = paper.get("title", "")
    reason = paper.get("reason", "")

    return f"""\
Use the $tcs-daily skill.

你正在为 {dt} 的日报撰写对一篇论文的深度解读。

## 论文
- arXiv: {aid}
- 标题: {title}
- 入选理由: {reason}

## 知识库中的相关记忆
{memory_ctx}

## 步骤

1. `tcs-daily extract {aid}` 读取论文全文（已预提取，秒回）。
   返回的 JSON 包含 abstract, introduction, main_results, techniques, conclusion, full_text。
   如果某个 section 为空，在 full_text 中搜索你需要的内容。
   **严禁自己写 PDF 解析脚本或安装额外 PDF 工具。**
2. 需要更多上下文就 `tcs-daily memory search/entries/topics`。

然后写一篇深度解读，存入 `data/cache/drafts/{dt}/{aid}.md`。

**📌 写作前先 `cat posts/2026-03-05.md`，这是风格标杆。** 注意它如何在正文中解释概念、如何控制旁注数量（全文仅 1 个）、以及每篇结尾的差异化处理。

## 写作要求

你有充分的自由来组织解读的结构。**不要**使用固定的编号式章节（"1. 背景" "2. 贡献" "3. 技术" "4. 展望"）。
根据论文特点选择最自然的叙事方式：有的论文适合从一个问题引入，有的适合从一个观察出发，有的适合先讲技术再回到动机。

但无论怎么组织，以下内容必须覆盖到位：

### 背景与脉络（这是最重要的，占最多篇幅）

**读者是有 CS 基础但完全不了解这个子方向的人。** 你需要从零开始把他们带进来：

- **动机**：这个子领域为什么存在？解决什么类型的问题？为什么有人关心？
  用日常语言说清楚，不要上来甩术语。
- **核心对象**：先用直觉说它在做什么，再给形式化定义。
  例：不要上来就写 $\\mathrm{{LDA}}^{{(m)}}_{{\\le k}}(P,Q)$ 的公式——先说"low-degree method
  是判断一个统计问题是否在多项式时间内可解的经验性工具"，然后再给公式。
- **研究脉络**：已有经典结果、谁在什么时候证了什么 bound（给作者年份，重要结果附 arXiv 链接），
  state-of-the-art，主要 open problems。**这部分不能省略或压缩**——它是读者理解本文价值的唯一入口。
- **本文定位**：这篇论文具体推进了什么？与已有结果的差距在哪里？

对正文中首次出现的非本科水平概念，**必须在正文中用自然语言解释清楚**。
不要把核心概念解释扔进旁注——旁注是折叠/侧栏的补充信息，读者可能不展开。
旁注 `:::aside[概念名]` 只用于补充严格形式化定义、历史引用、技术细节延伸等，一篇用 1-3 个即可。

### 开头要求（非常重要）

- 第一段就要交代清楚：**这篇论文研究什么问题、对象是什么、主结果是什么**
- 先给对象和 theorem，再给评价；不要先写气氛、判断或修辞
- 读者在前两段内必须能回答："这篇论文到底在研究什么"

**推荐句式：**
- "这篇论文研究的是 X：给定 ……，目标是 ……"
- "作者考虑的模型是 ……；主要结果是 ……"
- "背景问题是 ……；本文解决的是其中的 …… 版本"

**禁止句式：**
- ❌ "这篇 paper 讨论的是一个很‘供应链’、但算法味道很重的问题"
- ❌ "这篇论文真正钉住的，不是……而是……"
- ❌ "这件事背后有一个更大的问题意识"
- ❌ 先抛空泛评价，再迟迟不说具体问题
- ❌ 用带引号的口语标签词代替解释，例如"很‘工程’""很‘反直觉’"

### 技术内容

- 主要定理/算法的精确陈述（用 LaTeX）和与 prior best 的定量比较
- 关键 technical idea / proof strategy——不需要完整证明，但要让读者理解为什么方法能 work
- 与之前方法的本质区别、核心中间引理（如果有）
- **深入讲解而非罗列**：把技术思路写成连贯叙事，不要写成 bullet list 摘要

### 个人判断

- 融入行文中，不要单列一节。可以在技术分析中穿插你的看法
- **不要**每篇都在结尾写一段"价值→局限→open problems"的三段式评价
- 你的判断应该是具体的、不可替换的——读者看完应该觉得"这个人确实理解了论文"，而不是"这段评价套在任何论文上都成立"
- 好的个人判断例子："技术上最让我意外的是第二步：他们不是直接 derandomize 已有的随机算法，而是发现原问题有一个完全不同的确定性入口"
- 坏的个人判断例子："这篇工作的价值在于推进了该方向的前沿。局限也很明确。自然的后续问题是…"

## 写作规范（关键！）

### 数学公式
- 行内数学：`$...$`（例：$\\alpha = 1/\\mathrm{{poly}}(n)$）
- 块级数学：`$$...$$`
- **绝对不要**用反引号 `` ` `` 包裹数学表达式
- **绝对不要**用 `\\(...\\)` 或 `\\[...\\]`
- 算子名用 `\\mathrm{{}}` 包裹

### 链接
- arXiv 链接：`[arXiv:{aid}](https://arxiv.org/abs/{aid.rstrip('v1234567890')})`
- 往期日报链接必须使用 hash route：`[2026-03-05 日报](#2026-03-05)`
- 作者引用格式：`作者 (年份)` 或 `作者 et al. (年份)`，重要结果附 arXiv 链接

### 旁注
- 旁注是**补充信息**，不是概念讲解区。正文必须自包含，不展开旁注也能读懂
- 适合放旁注的：严格形式化定义（正文已讲清直觉）、历史引用、技术细节延伸
- **不要**把核心概念首次解释放在旁注里
- 语法：`:::aside[概念名]` ... `:::`
- 一篇解读用 1-3 个旁注就够了，不要滥用

### 篇幅
- 通常 **3000-6000 字**（中文字符）。背景和技术讲解是大头，宁可多花笔墨也不要让读者看不懂。
- 技术确实简单的论文可以 1500 字，但不要人为压缩解释性内容。
- 检验方法：想象一个刚通过本科算法课的学生读你的文章——他能跟上吗？如果不能，是背景不够。

### 语气与个人声音
- 你是一个真正读了这篇论文的研究者，不是在写综述或 survey
- **允许并鼓励自然的个人反应**：如果某个 idea 确实漂亮，说清楚为什么漂亮（"这里最巧的一步是把 X 转化成 Y——初看不自然，但一旦做完，后面的分析就全部打开了"）；如果某处你吃了一惊，说出来（"我一开始以为他们会走 X 路线，结果完全不是"）
- 但**不要空洞感叹**：不要写"引人入胜""令人兴奋""很有味道"——这些词不传递信息
- 不要把评论腔写成分析。像"算法味很重""很供应链""真正钉住了一个结构判断"这类句子，如果后面没有立刻给出明确对象和定理，就一律不要写
- 中英混用，术语保留英文
- 不要用 emoji
- 不要写"综上所述""总而言之"
- 不要写大段关于 PDF 提取质量的声明——如果有问题，在具体位置行内提一句即可

### ⚠️ 禁止套路化结尾
每一篇解读都必须有独特的收束方式。**严禁以下模板**：
- ❌ "这篇工作的价值在于…局限也很明确/清楚…自然的 follow-up 是…"（三段式评价模板）
- ❌ 单列一节叫"评价与展望""讨论""总结"
- ❌ 每篇都以 open problems 列表结尾
- ❌ "局限也很明确""局限也很清楚"这类机械过渡

**好的收束方式因文而异**：
- 可以在最后一个技术分析后自然停住，不另写总结
- 可以用一句关于 open problem 的个人判断结尾（但不要每篇都这样）
- 可以把评价散在行文各处，结尾只是技术讨论的自然收尾
- 可以以一个观察或联想结尾（"这和上周 X 的工作形成了有趣的对比"）
- 有的论文结束就结束了，不需要画蛇添足

## 更新记忆

写完后更新知识库：
- `tcs-daily memory record-paper '{{...}}'` — 记录论文（必须）
- `tcs-daily memory link-topic {aid} "topic"` — 关联主题
- `tcs-daily memory record-entry <key> <value> <category>` — 记录你觉得将来有用的知识
  （category: result | technique | concept | open_problem | definition）
"""


def prompt_assembly(dt: str, draft_files: list[str], selection_rel: str) -> str:
    listing = "\n".join(f"- `{f}`" for f in draft_files)
    n = len(draft_files)

    return f"""\
Use the $tcs-daily skill.

今天是 {dt}，你手里有 {n} 篇独立完成的论文解读。

## 稿件
{listing}

用 `cat` 逐个读取上面的文件。也读取 `{selection_rel}` 查看筛选结果。
开始编辑前先运行一次 `tcs-daily tags`，确认最终稿里使用的 tag 都来自允许集合。

## 任务

组装最终日报，写入 `posts/{dt}.md`。

### 结构

1. **YAML frontmatter**：
   ```
   ---
   date: {dt}
   ---
   ```

2. **编辑按语**（`## 编辑按语`）：
   - 用 2-3 段文字概述今天选了哪些论文、分别属于什么方向
   - **诚实描述**：如果今天的论文来自不同子方向且没有实际联系，就说"今天的论文覆盖了 X、Y、Z 几个不同方向"——**不要编造主题联系**
   - 只有当论文之间确实有技术/问题上的关联时才指出（例如两篇都在做 sparse PCA）
   - 不要写"共同底色""重画叙事"之类的空泛叙事弧——读者会立刻看出来这是硬编的
   - 不超过 300 字

3. **每篇论文的解读**，每篇必须用 `::::issue[tags]` 块包裹：
   - 格式：
     ```
     ::::issue[tag1, tag2]
     ## 论文标题 [arXiv:XXXX.XXXXX](https://arxiv.org/abs/XXXX.XXXXX)
     ...完整解读...
     ::::
     ```
   - `::::issue` 使用四个冒号（和旁注 `:::aside` 的三个冒号区分）
   - 方括号内填写该论文的 tags（从 SKILL.md 预定义标签体系中选取，小写 kebab-case）
     **默认每篇 1 个 tag**；只有论文确实横跨两个独立方向时才用 2 个
     **只能**使用 `tcs-daily tags` 返回的 tag key
     **不要用** `algorithms` `complexity` `graph-theory` 这种一级大类——用二级子方向标签
     **不要新建 tag**
   - 保留原稿的深度分析和数学公式
   - 可以润色语言、删除冗余，但核心 technical 内容不要丢
   - 可以调整论文顺序、加过渡句

4. **未入选但值得关注**（`## 未入选但值得关注`）：
   - 从 selection JSON 的 `skipped_notable` 中提取
   - 每篇 1-2 句话说明论文做了什么、为什么没选

### ⚠️ 关键：数学公式处理

稿件中的数学公式使用 `$...$` 和 `$$...$$` 语法。
在组装过程中你 **必须原样保留所有数学公式**。

- **绝对不要**把 `$...$` 改成反引号 `` ` ``
- **绝对不要**把 `$$...$$` 改成代码块
- **绝对不要**把 `\\(` `\\)` 或 `\\[` `\\]` 改成反引号
- 如果你在稿件中看到任何形式的 LaTeX 数学（`$`, `$$`, `\\(`, `\\[`），
  在最终输出中**一律使用 `$` 和 `$$`**

这是最重要的规则。数学公式如果被转成 backtick code，整份日报就废了。

### 编辑要求

**📌 编辑前先 `cat posts/2026-03-05.md`，这是风格标杆。** 以它为标准检查每篇稿件的概念解释方式、旁注用量和结尾处理。

你是编辑，不是复制粘贴机，但也**不是压缩机**。你应该：

**保留深度：**
- 原稿的背景段落、技术分析、数学公式必须完整保留——这些是文章的核心价值
- 如果原稿的背景不够充分（读者可能看不懂），你应该**补充**而不是删减
- 每篇最终至少 3000 字（中文字符），除非论文技术确实简单
- 如果原稿开头是悬浮评论腔，先重写开头：把第一段改成"问题 / 模型 / 主结果"三件事先讲清楚

**结构自由：**
- 不要给原稿强套 "1. 背景 → 2. 贡献 → 3. 技术 → 4. 展望" 编号结构
- 如果原稿的组织方式更自然（例如从一个 observation 引入），保留它
- 删掉 "评价与展望""讨论""总结" 这样的套路标题——个人判断融入行文即可

**⚠️ 打破结尾套路：**
- 检查每篇稿件的结尾段落。如果多篇都是"价值在于…局限在于…follow-up 是…"三段式，**必须改写**
- 每篇解读的结束方式应该不同：有的在技术分析后自然收束，有的以一个观察结尾，有的根本不需要额外总结
- 删除所有"局限也很明确/清楚""自然的 follow-up 是"这类机械过渡句
- 如果原稿评价已经很好地融入了行文，就不要在末尾再加总结段

**概念覆盖检查：**
- 读一遍每篇文章，列出所有非本科水平的技术术语
- 检查每个术语是否在**正文中**有解释（用自然语言讲清楚直觉和作用）
- 如果有裸用的术语，**在正文中添加解释**，不要只往旁注里扔
- 旁注仅用于补充严格定义、历史引用、延伸细节——读者不展开旁注也必须能读懂全文
- 如果原稿旁注过多（超过 3 个）或旁注里放了核心解释，把重要内容搬回正文

**其他编辑：**
- 统一术语——同一概念在不同稿件中的称呼应一致
- 删除重复（如果两篇稿件都解释了同一个概念，保留更好的那个）
- 删除冗余的 PDF 提取质量声明
- 润色语言，但不要改变技术内容
- **通读一遍所有稿件，检查是否有重复句式/结构**——如果多篇都用了相同的过渡句、相同的段落结构、或相同的结尾模式，改写使每篇有独特语感
- 特别检查开头两段：凡是出现"这篇 paper 讨论的是一个很 X 的问题"、"真正钉住的不是……而是……"、"背后有一个更大的问题意识"这类 AI 式开场，全部改写成直接说明问题对象和结果

### 写作规范

- 标题从 `##` 开始，不用 `#`
- 不要用 emoji
- 不要写"综上所述""总体来看"之类的套话
- 不要每篇结尾都加一段总结——如果评价已经融入分析中了，就不需要单独总结段
- 开头不要写悬浮评价句；首段必须让读者知道问题、模型和结果
- arXiv 链接必须是可点击的 Markdown 超链接
- 往期日报链接必须写成 hash route：`[2026-03-05 日报](#2026-03-05)`；不要写 `../posts/2026-03-05.md`

完成后：
- `tcs-daily manifest {dt} posts/{dt}.md {n}`
- `tcs-daily validate {dt}`
"""


# ── main ───────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-stage TCS daily pipeline via codex exec.")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--model", default="")
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
        selected_ids = ", ".join(p["arxiv_id"] for p in selected) if selected else "(none)"
        _log(f"[selection] {len(selected)} papers: {selected_ids}")
    else:
        selected = [{"arxiv_id": "XXXX.XXXXXv1", "title": "(example)", "tags": ["exact-algorithms"], "reason": "…"}]

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
                pending = [p for p in pending if p["arxiv_id"] not in failed]
            _log(f"[stage 2] ready for drafting: {len(pending)}")

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
                    # continue with remaining papers

    # ════════════════════════════════════════════════════════════
    #  Stage 3 — assembly
    # ════════════════════════════════════════════════════════════
    if run_stage in (None, 3):
        can_reuse_report = (
            not args.dry_run
            and 3 not in force_stages
            and _looks_complete(report_path, min_size=2000)
        )
        if can_reuse_report:
            cached_validation = tool("validate", dt)
            can_reuse_report = bool(cached_validation and cached_validation.get("ok"))

        if can_reuse_report:
            _log("[stage 3] reusing existing validated report")
        else:
            _log("[stage 3] assembling report")

            if not args.dry_run:
                drafts = sorted(drafts_dir.glob("*.md"))
                draft_rels = [str(d.relative_to(ROOT)) for d in drafts]
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
    result = tool("validate", dt)
    if result and result.get("ok"):
        _log("[done] outputs validated")
    else:
        errs = result.get("errors", []) if result else ["validation failed"]
        _log(f"[done] validation issues: {errs}")


if __name__ == "__main__":
    main()
