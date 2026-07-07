# Carbon Market Due Diligence v1

Short name: `carbon-dd-v1`

A carbon-project due-diligence workbench. It ingests the public documents behind a
carbon-credit project (Project Description Documents, validation, monitoring and
verification reports), turns them into a structured, cited, auditable evidence base,
runs deterministic screening rules, and produces a reviewer memo plus a printable
HTML review pack — with an append-only audit trail and a hash-verified case-memory
snapshot at every step.

Guiding principle: the system records **what is known, what is missing, and what
requires judgment — it does not make the judgment.**

## What it does NOT do

- It does **not** make eligibility, legal, or investment determinations.
- It does **not** decide whether credits are valid or a project passes.
- It surfaces material signals and evidence gaps for a human reviewer, and every
  system-generated finding is labelled as requiring human review.

## Two ways to run it

### 1. Streamlit app (interactive)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Seven tabs:

1. **Project** — identity, registry status, and any critical findings at a glance.
2. **Documents** — held documents, expected-but-missing documents, and a PDF uploader
   that ingests and re-runs the pipeline.
3. **AI Proposals** — review AI-extracted candidate facts; confirm / edit / reject
   (human-in-the-loop). No-op without an OpenAI key.
4. **Facts** — confirmed facts with source chunks, propose new facts, author evidence cards.
5. **Findings** — deterministic screening results by severity, with reviewer
   dispositions and (optional) AI analysis per finding.
6. **Memo** — generate and download the reviewer memo (Markdown) and review pack (HTML).
7. **Audit Trail** — the append-only event log and the hash-verified case-memory snapshot.

### 2. Command-line pipeline (deterministic)

```bash
python scripts/run_pipeline.py                 # default project (project_9199)
python scripts/run_pipeline.py project0001     # any registered project
python scripts/run_pipeline.py --list          # list registered projects
```

Other entry points:

```bash
python scripts/run_ingestion.py <project_id>       # parse documents + AI extraction
python scripts/build_review_pack.py <project_id>   # build the HTML review pack
python scripts/run_memo.py                         # legacy project_9199 memo only
```

## Multi-project support

Projects live in `data/projects/registry.json`; each project's data is laid out
per-project by `core/paths.py`. Three projects ship with the repo:

- `project_9199` — UNFCCC CDM Project 9199, forestry restoration in Colombia
  (deregistered March 2022). CDM A/R rule set. The original seed case.
- `project_test_vcs_001` — a generic VCS demo. Generic rule set.
- `project0001` — HFC-23 thermal-oxidation project, Gujarat, India. CDM A/R rule set.

The rule set applied is chosen by the project's `methodology_type`
(`cdm_ar` → CDM A/R rules; anything else → generic rules).

### Add a new project

Either use **"+ New project"** in the Streamlit sidebar, or call
`core.project_manager.create_project(...)`. Project IDs must be 3–50 characters,
lowercase letters, numbers, and underscores only. This scaffolds the per-project
folders and empty facts/evidence files and appends an entry to the project registry.
Optionally add a `reviewer_questions` list to the registry entry to give that project
its own curated reviewer questions; otherwise the memo derives one question per finding.

### Get real documents into the system

Place PDFs (or `.txt`/`.md`) in `data/documents/raw/<project_id>/`, or upload PDFs
through the Documents tab. Ingestion parses each document into page/paragraph chunks
and citations under `data/documents/processed/<project_id>/` and records them in
`data/documents/registry.json`.

## AI features (optional)

AI fact extraction and per-finding narrative generation use OpenAI and are gated on
the `OPENAI_API_KEY` environment variable. Without a key, the system runs fully
deterministically: extraction and narratives are skipped and clearly marked as
unavailable — nothing else is affected. AI-drafted text is always labelled as
grounded-but-requiring-human-review.

## Outputs (per project)

- Reviewer memo: `data/outputs/memos/<project_id>_memo.md`
- Review pack: `data/outputs/<project_id>_review_pack.html`
- Audit log: `data/outputs/audit_logs/<project_id>.jsonl`
- Case memory snapshot: `data/outputs/case_memory/<project_id>_snapshot.json`

## Test

```bash
python -m pytest tests/ -v
```

## Requirements

Python >= 3.10. Runtime dependencies: `pdfplumber` (PDF parsing), `streamlit` (the
app), and `openai` (optional AI features; imported lazily and only used when
`OPENAI_API_KEY` is set). See `requirements.txt` / `pyproject.toml`.

## Known limitations

- Findings are computed on demand and recorded as audit events; they are not
  persisted as standalone records, and reviewer dispositions are stored separately
  and do not feed back into the rule logic.
- `risk_flags.py` and the rule functions both carry flag severity/description, so
  those two sources can drift.
- Storage is last-write-wins JSON files; concurrent edits to the same project can
  clobber one another.
- AI extraction is single-vendor (OpenAI `gpt-4o`) with no provider abstraction.
- `scripts/run_memo.py` is a legacy `project_9199`-only path retained for convenience;
  prefer `scripts/run_pipeline.py`.
