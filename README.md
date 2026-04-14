# tcs-daily

TCS (Theoretical Computer Science) daily reading report generator, powered by [Codex CLI](https://github.com/openai/codex).

## Architecture

Python provides **tool interfaces** only — all analysis, writing, and editorial decisions are made by Codex autonomously.

```
run_codex.py          ← entry point: prefetch → codex exec → validate
  ↓
codex exec            ← the agent, using .agents/skills/tcs-daily/SKILL.md
  ↓ calls
tcs-daily fetch       ← theory.report + arXiv metadata
tcs-daily download    ← PDF download
tcs-daily extract     ← PDF text extraction
tcs-daily memory ...  ← persistent knowledge base (SQLite)
tcs-daily manifest    ← manifest.json update
tcs-daily validate    ← output checks
  ↓ produces
posts/YYYY-MM-DD.md   ← daily report
posts/manifest.json    ← report index
memory.db             ← accumulated knowledge
```

## Quick Start

```bash
# Install
python3 -m pip install -e .

# Generate today's report
python3 run_codex.py

# Generate for a specific date
python3 run_codex.py --date 2026-03-04

# Dry run (see what would be sent to Codex)
python3 run_codex.py --dry-run

# Use a specific model
python3 run_codex.py --model o3
```

## CLI Tools

All tools output JSON to stdout. They are designed for Codex to call, but can be used standalone.

```bash
tcs-daily fetch <date>                # Fetch candidates + arXiv metadata
tcs-daily metadata <arxiv_id>         # arXiv metadata for one paper
tcs-daily download <arxiv_id>         # Download PDF
tcs-daily extract <arxiv_id>          # Extract PDF text sections
tcs-daily tags                        # Canonical allowed report tags
tcs-daily history <query>             # Search past reports
tcs-daily manifest <date> <path> <n>  # Update manifest.json
tcs-daily validate <date>             # Check outputs

tcs-daily memory search <query>       # Search papers in knowledge base
tcs-daily memory topics [query]       # List/search topics
tcs-daily memory entries <query>      # Search knowledge entries
tcs-daily memory paper <arxiv_id>     # Get one paper's record
tcs-daily memory date <date>          # Get papers from a date
tcs-daily memory record-paper <json>  # Record a paper
tcs-daily memory link-topic <id> <t>  # Link paper to topic
tcs-daily memory record-entry <k><v><c> # Record knowledge entry
tcs-daily memory stats                # KB statistics
```

## Data Sources

- [theory.report](https://theory.report) — daily TCS paper aggregator
- [arXiv API](https://arxiv.org/help/api) — paper metadata and PDFs

## Frontend

The frontend SPA (`index.html`, `style.css`, `app.js`) lives at the repo root.
Reports are served from `posts/` as markdown.

```bash
# Local preview
python3 serve.py         # → http://localhost:8000/
```

### Deployment

Copy the frontend files and `posts/` into the target web directory (e.g.
`bzy-nya.github.io/tcs-daily/`):

```bash
rsync -a index.html style.css app.js ../bzy-nya.github.io/tcs-daily/
rsync -a posts/ ../bzy-nya.github.io/tcs-daily/posts/
```

## Project Structure

```
.agents/skills/tcs-daily/SKILL.md  ← Codex skill definition
run_codex.py                       ← entry point
serve.py                           ← development server
index.html                         ← SPA entry point
style.css                          ← stylesheet
app.js                             ← hash-router + marked.js renderer
tcs_daily/                         ← Python package (tools only)
  cli.py                           ← CLI argument parsing + dispatch
  config.py                        ← path layout
  fetch.py                         ← theory.report + arXiv fetching
  pdf.py                           ← PDF download + text extraction
  memory.py                        ← SQLite knowledge base
  cache.py                         ← JSON cache read/write
  _http.py                         ← HTTP with TLS/UA handling
references/                        ← curated notes and surveys
posts/                             ← generated reports + manifest
data/                              ← caches (gitignored)
memory.db                          ← persistent knowledge base
```
