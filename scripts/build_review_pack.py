from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memo import DISCLAIMER_TEXT, reviewer_questions_for  # noqa: E402
from core.paths import ProjectPaths  # noqa: E402
from core.project_manager import get_project  # noqa: E402
from domain.project_9199 import PROJECT_9199_FACTS  # noqa: E402
from domain.risk_flags import RISK_FLAGS  # noqa: E402
from domain.rule_router import run_checks_for_project  # noqa: E402

DEFAULT_PROJECT_ID = "project_9199"
_DEFAULT_PATHS = ProjectPaths(DEFAULT_PROJECT_ID, base_dir=ROOT)
CARDS_PATH = _DEFAULT_PATHS.evidence_cards_file
AUDIT_PATH = _DEFAULT_PATHS.audit_log
SNAPSHOT_PATH = _DEFAULT_PATHS.case_memory
NARRATIVES_PATH = _DEFAULT_PATHS.narratives
OUTPUT_PATH = _DEFAULT_PATHS.review_pack

DEFAULT_CRITICAL_FLAGS = ["AR_DEREG_001", "AR_ISS_GAP_001"]

FACT_IDENTITY_KEYS = (
    "title",
    "validator_name",
    "verifier_name",
    "registration_date",
    "deregistration_date",
    "crediting_period_start",
    "crediting_period_end",
    "annual_reductions_claimed_tco2e",
    "first_issuance_amount_cers",
    "second_issuance_amount_cers",
    "additionality_approach",
    "permanence_risk_addressed",
    "monitoring_period_end",
)

FIELD_LABELS = {
    "project_id": "Project ID",
    "title": "Project Title",
    "host_country": "Host Country",
    "sectoral_scope": "Sectoral Scope",
    "methodology": "Methodology",
    "baseline_methodology_ref": "Baseline Methodology",
    "activity_scale": "Activity Scale",
    "validator_name": "Validator (DOE)",
    "verifier_name": "Verifier (DOE)",
    "registration_date": "Registration Date",
    "deregistration_date": "Deregistration Date",
    "crediting_period_start": "Crediting Period Start",
    "crediting_period_end": "Crediting Period End",
    "annual_reductions_claimed_tco2e": "Annual Emission Reductions Claimed (tCO\u2082e)",
    "first_issuance_amount_cers": "First Period Issuance (CERs)",
    "second_issuance_amount_cers": "Second Period Issuance (CERs)",
    "second_issuance_status": "Second Period Status",
    "host_party_approval": "Host Party Approval",
    "host_party_approval_document": "Host Party Approval Document",
    "voluntary_cancellations_cers": "Voluntary Cancellations (CERs)",
    "cancellations_exceed_second_period_by_cers": "Cancellations Exceed Second Period Balance (CERs)",
    "additionality_approach": "Additionality Approach",
    "permanence_risk_addressed": "Permanence Risk Addressed",
    "monitoring_period_end": "Monitoring Period End",
    "source": "Data Source",
    "source_url": "Registry URL",
    "data_class": "Data Classification",
    "limitations": "Limitations",
}

SKIP_PROJECT_TABLE_KEYS = {"limitations", "data_class"}


def main(project_id: str = DEFAULT_PROJECT_ID) -> None:
    paths = ProjectPaths(project_id, base_dir=ROOT)
    facts = _project_identity_facts(project_id, paths)
    cards = _read_json_or_default(paths.evidence_cards_file, [])
    audit_events = _read_jsonl(paths.audit_log)
    snapshot = _read_json_or_default(paths.case_memory, {})
    confirmed_fact_count = _confirmed_fact_count(paths)
    pending_proposal_count = _pending_proposal_count(paths)
    provisional = confirmed_fact_count == 0

    if provisional:
        # Nothing is confirmed, so rule hits and AI narratives would assert that
        # facts are absent when they are merely unconfirmed. Withhold them.
        narratives: dict[str, str] = {}
        critical_flags: list[str] = []
        reviewer_questions: list[str] = []
    else:
        narratives = _load_narratives_for(paths.narratives)
        critical_flags = _critical_flags_for(project_id, facts)
        reviewer_questions = _reviewer_questions_for(project_id, facts, paths)
    generated_at = datetime.now(timezone.utc)

    html = build_html(
        project_id=project_id,
        facts=facts,
        cards=cards,
        audit_events=audit_events,
        snapshot=snapshot,
        narratives=narratives,
        critical_flags=critical_flags,
        reviewer_questions=reviewer_questions,
        generated_at=generated_at,
        provisional=provisional,
        pending_proposal_count=pending_proposal_count,
    )
    paths.review_pack.parent.mkdir(parents=True, exist_ok=True)
    paths.review_pack.write_text(html, encoding="utf-8")
    status = "provisional" if provisional else "full"
    print(f"Review pack ({status}): {paths.review_pack.relative_to(ROOT)}")


def _project_identity_facts(project_id: str, paths: ProjectPaths) -> dict[str, Any]:
    if project_id == DEFAULT_PROJECT_ID:
        return dict(PROJECT_9199_FACTS)
    registry_entry = (
        get_project(project_id, str(paths.project_registry)) or {}
    )
    facts: dict[str, Any] = {
        "project_id": project_id,
        "title": registry_entry.get("display_name", project_id),
        "host_country": registry_entry.get("host_country"),
        "methodology": registry_entry.get("methodology"),
        "methodology_type": registry_entry.get("methodology_type"),
        "status": registry_entry.get("status"),
        "document_count": registry_entry.get("document_count"),
        "facts_count": registry_entry.get("facts_count"),
        "findings_count": registry_entry.get("findings_count"),
        "created_at": registry_entry.get("created_at"),
    }
    if paths.facts_file.exists():
        records = json.loads(paths.facts_file.read_text(encoding="utf-8"))
        for record in records:
            label = (record.get("label") or "").strip().lower().replace(" ", "_")
            if label in FACT_IDENTITY_KEYS:
                facts[label] = record.get("value")
    facts["limitations"] = [
        "Project identity derived from registry record and confirmed facts.",
        "Primary document verification not yet complete.",
    ]
    facts.setdefault("source", "Carbon DD v1 project registry")
    facts.setdefault("data_class", "registry_plus_confirmed_facts")
    return facts


def _critical_flags_for(project_id: str, facts: dict[str, Any]) -> list[str]:
    if project_id == DEFAULT_PROJECT_ID:
        return list(DEFAULT_CRITICAL_FLAGS)
    methodology_type = facts.get("methodology_type") or "generic"
    findings = run_checks_for_project(facts, methodology_type)
    if not findings:
        return []
    severity_priority = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    findings.sort(
        key=lambda finding: (severity_priority.get(finding.severity, 99), finding.flag_code)
    )
    selected = [finding.flag_code for finding in findings if finding.severity == "Critical"]
    if not selected:
        selected = [finding.flag_code for finding in findings[:3]]
    return selected


def _reviewer_questions_for(project_id: str, facts: dict[str, Any], paths: ProjectPaths) -> list[str]:
    project_record = get_project(project_id, str(paths.project_registry)) or {}
    methodology_type = project_record.get("methodology_type") or (
        "cdm_ar" if project_id == DEFAULT_PROJECT_ID else "generic"
    )
    findings = run_checks_for_project(facts, methodology_type)
    return reviewer_questions_for(project_record, findings)


def _confirmed_fact_count(paths: ProjectPaths) -> int:
    records = _read_json_or_default(paths.facts_file, [])
    return len(records) if isinstance(records, list) else 0


def _pending_proposal_count(paths: ProjectPaths) -> int:
    records = _read_json_or_default(paths.proposals_file, [])
    if not isinstance(records, list):
        return 0
    return sum(1 for record in records if record.get("status") == "pending")


def _read_json_or_default(path: Path, default: Any) -> Any:
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_narratives_for(narratives_path: Path) -> dict[str, str]:
    if not Path(narratives_path).exists():
        return {}
    payload = json.loads(Path(narratives_path).read_text(encoding="utf-8"))
    narratives = payload.get("narratives", {})
    return {str(k): str(v) for k, v in narratives.items()}


def build_html(
    facts: dict[str, Any],
    cards: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    snapshot: dict[str, Any],
    generated_at: datetime,
    narratives: dict[str, str] | None = None,
    project_id: str = DEFAULT_PROJECT_ID,
    critical_flags: list[str] | None = None,
    reviewer_questions: list[str] | None = None,
    provisional: bool = False,
    pending_proposal_count: int = 0,
) -> str:
    critical_flags = critical_flags if critical_flags is not None else list(DEFAULT_CRITICAL_FLAGS)
    if provisional:
        body = [
            _provisional_notice(pending_proposal_count),
            _project_identity(project_id, facts),
            _evidence_cards(cards),
            _audit_trail(audit_events, snapshot),
            _case_memory(snapshot),
        ]
    else:
        body = [
            _critical_signals(critical_flags, narratives or {}),
            _project_identity(project_id, facts),
            _evidence_cards(cards),
            _reviewer_questions(reviewer_questions or []),
            _evidence_gaps(critical_flags),
            _audit_trail(audit_events, snapshot),
            _case_memory(snapshot),
        ]
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>Carbon Market Due Diligence \u2014 {escape(project_id)} Review Pack</title>",
            _style(),
            "</head>",
            "<body>",
            _header(project_id, facts, generated_at),
            '<main class="page">',
            *body,
            "</main>",
            _footer(),
            "</body>",
            "</html>",
        ]
    )


def _provisional_notice(pending_proposal_count: int) -> str:
    return f"""<section class="section">
  <h2>Status \u2014 Provisional</h2>
  <span class="label">[STATUS \u2014 PROVISIONAL, no facts confirmed]</span>
  <article class="card critical-card">
    <p><strong>STATUS: Provisional \u2014 no facts confirmed yet.</strong></p>
    <p>This project has {escape(str(pending_proposal_count))} AI-extracted proposals awaiting
    human confirmation. Findings and evidence assessment cannot be produced until facts are
    confirmed. This review pack is a placeholder.</p>
    <p class="required"><strong>Next step:</strong> confirm proposals in the AI Proposals tab,
    rerun the pipeline, then regenerate this review pack.</p>
  </article>
</section>"""


def _style() -> str:
    return """<style>
:root {
  --ink: #18212f;
  --muted: #647084;
  --line: #d8dee8;
  --panel: #ffffff;
  --page: #f4f6f8;
  --header: #111827;
  --critical: #b42318;
  --critical-soft: #fff1f0;
  --green: #16803c;
  --green-soft: #eaf7ee;
  --amber: #a15c00;
  --amber-soft: #fff5df;
  --red: #b42318;
  --red-soft: #fff1f0;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
.hero {
  background: var(--header);
  color: white;
  padding: 28px 32px;
  border-bottom: 4px solid var(--critical);
}
.hero-inner, .page, .footer-inner {
  max-width: 1200px;
  margin: 0 auto;
}
.system-name {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
}
.project-line, .generated-line {
  margin: 3px 0;
  color: #d6dde8;
}
.status-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.page { padding: 28px 24px 40px; }
.section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 2px rgba(20, 30, 45, 0.05);
}
h2 { margin: 0 0 14px; font-size: 20px; letter-spacing: 0; }
h3 { margin: 0 0 8px; font-size: 16px; }
.label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  margin-bottom: 12px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  background: #fff;
}
.critical-card {
  border-color: #f0b4ae;
  background: var(--critical-soft);
}
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.badge-critical, .badge-contradicts { background: var(--red-soft); color: var(--red); border: 1px solid #f0b4ae; }
.badge-supports { background: var(--green-soft); color: var(--green); border: 1px solid #a9ddb8; }
.badge-needs { background: var(--amber-soft); color: var(--amber); border: 1px solid #f3cd89; }
.badge-review { background: #eef2f7; color: #465266; border: 1px solid #d8dee8; }
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0;
}
.required { margin: 10px 0 0; color: #334155; }
.ai-narrative {
  margin: 12px 0 4px;
  padding: 10px 12px;
  border-left: 3px solid #2563eb;
  background: #f4f7fc;
  color: #1f2a3d;
  font-style: italic;
  border-radius: 4px;
}
.ai-label {
  display: block;
  margin: 4px 0 0;
  color: #647084;
  font-size: 11px;
  letter-spacing: 0.04em;
  font-weight: 700;
  text-transform: uppercase;
  font-style: normal;
}
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
  padding: 9px 10px;
}
th {
  background: #f8fafc;
  font-size: 13px;
  color: #465266;
}
.field-name {
  width: 28%;
  font-weight: 700;
  color: #2f3a4c;
}
.muted { color: var(--muted); font-size: 13px; }
.questions li { margin-bottom: 18px; }
.response-line {
  margin-top: 8px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  min-height: 24px;
}
.audit-table { font-size: 13px; }
.audit-table td:nth-child(1) { width: 30%; }
.audit-table td:nth-child(2) { width: 20%; }
.hash {
  overflow-wrap: anywhere;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
}
footer {
  padding: 22px 24px 34px;
  color: var(--muted);
  font-size: 12px;
}
@media (max-width: 760px) {
  .grid { grid-template-columns: 1fr; }
  .status-row { display: block; }
  .badge { margin-top: 10px; }
  .page { padding: 18px 12px; }
  .section { padding: 16px; }
}
@media print {
  body, .hero, .section, th, .card, .critical-card, .badge {
    background: white !important;
    color: black !important;
    box-shadow: none !important;
  }
  .hero { border-bottom: 1px solid black; }
  .section, .card, .badge { border-color: #999 !important; }
  a { color: black; }
}
</style>"""


def _header(project_id: str, facts: dict[str, Any], generated_at: datetime) -> str:
    generated_label = generated_at.strftime("%d %B %Y at %H:%M UTC")
    status = str(facts.get("status") or "").strip()
    if project_id == DEFAULT_PROJECT_ID:
        project_line = "Project: 9199 \u2014 Forestry Restoration, Colombia"
        status_label = "DEREGISTERED"
        status_class = "badge-critical"
    else:
        title = facts.get("title") or project_id
        host = facts.get("host_country") or "(host country unknown)"
        project_line = f"Project: {project_id} \u2014 {title}, {host}"
        status_label = status.upper() if status else "UNKNOWN"
        status_class = {
            "deregistered": "badge-critical",
            "active": "badge-supports",
            "registered": "badge-review",
        }.get(status.lower(), "badge-review")
    return f"""<header class="hero">
  <div class="hero-inner status-row">
    <div>
      <h1 class="system-name">Carbon Market Due Diligence v1</h1>
      <p class="project-line">{escape(project_line)}</p>
      <p class="generated-line">Generated: {escape(generated_label)}</p>
    </div>
    <span class="badge {status_class}">{escape(status_label)}</span>
  </div>
</header>"""


def _critical_signals(critical_flags: list[str], narratives: dict[str, str] | None = None) -> str:
    narratives = narratives or {}
    if not critical_flags:
        return """<section class="section">
  <h2>Critical Signals</h2>
  <p class="muted">No critical-severity findings were produced by the deterministic rule engine for this project.</p>
</section>"""
    cards = []
    for flag in critical_flags:
        meta = RISK_FLAGS.get(flag)
        if meta is None:
            continue
        cancellation_note = ""
        if flag == "AR_ISS_GAP_001":
            cancellation_note = (
                "<p><strong>Note on cancellations:</strong> Voluntary cancellations "
                "recorded against this project total 1,257,195 CERs \u2014 exceeding "
                "the second period issuance balance of 374,589 CERs by 882,606 CERs. "
                "The relationship between these figures requires verification against "
                "registry serial records.</p>"
            )
        narrative_html = ""
        if flag in narratives:
            narrative_text = narratives[flag].strip()
            if narrative_text:
                narrative_html = (
                    f'<div class="ai-narrative"><p>{escape(narrative_text)}</p>'
                    '<span class="ai-label">AI-drafted analysis \u2014 grounded in '
                    'confirmed evidence, requires human review</span></div>'
                )
        severity = meta.get("severity", "Critical")
        title = meta.get("title", flag)
        description = meta.get("description", "")
        evidence_required = meta.get("evidence_required", [])
        cards.append(
            f"""<article class="card critical-card">
  <span class="badge badge-critical">{escape(severity)}</span>
  <h3>{escape(flag)} \u2014 {escape(title)}</h3>
  <p>{escape(description)}</p>
  {narrative_html}
  {cancellation_note}
  <p class="required"><strong>Required documents:</strong> {escape(_human_list(evidence_required))}</p>
</article>"""
        )
    return f"""<section class="section">
  <h2>Critical Signals</h2>
  <div class="grid">
    {''.join(cards)}
  </div>
</section>"""


def _project_identity(project_id: str, facts: dict[str, Any]) -> str:
    limitations = facts.get("limitations", [])
    label_text = (
        "[STRUCTURED DATA \u2014 UNFCCC Registry]"
        if project_id == DEFAULT_PROJECT_ID
        else "[PROJECT IDENTITY \u2014 registry record + confirmed facts]"
    )
    rows = []
    for key, value in facts.items():
        if key in SKIP_PROJECT_TABLE_KEYS:
            continue
        if value is None:
            continue
        rows.append(
            f'<tr><td class="field-name">{escape(_field_label(key))}</td><td>{_format_value(value, key)}</td></tr>'
        )
    limitation_items = "".join(f"<li>{escape(str(item))}</li>" for item in limitations)
    return f"""<section class="section">
  <h2>Project Identity</h2>
  <span class="label">{escape(label_text)}</span>
  <table>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <div class="muted">
    <p><strong>Limitations</strong></p>
    <ul>{limitation_items}</ul>
  </div>
</section>"""


def _evidence_cards(cards: list[dict[str, Any]]) -> str:
    rendered = []
    for card in cards:
        role = str(card.get("evidence_role", ""))
        role_class = {
            "supports": "badge-supports",
            "contradicts": "badge-contradicts",
            "needs_more_evidence": "badge-needs",
        }.get(role, "badge-review")
        reviewer_note = card.get("reviewer_note")
        note_html = f'<p class="muted"><strong>Reviewer note:</strong> {escape(str(reviewer_note))}</p>' if reviewer_note else ""
        rendered.append(
            f"""<article class="card">
  <p><strong>{escape(str(card.get("claim", "")))}</strong></p>
  <p><strong>Claim topic:</strong> {escape(str(card.get("claim_topic", "")))}</p>
  <div class="meta-row">
    <span class="badge {role_class}">{escape(role)}</span>
    <span class="badge badge-review">{escape(str(card.get("review_status", "")))}</span>
  </div>
  {note_html}
</article>"""
        )
    return f"""<section class="section">
  <h2>Evidence Cards</h2>
  <span class="label">[EVIDENCE CHAIN \u2014 manually curated, pending human review]</span>
  <div class="grid">
    {''.join(rendered)}
  </div>
</section>"""


def _reviewer_questions(questions: list[str]) -> str:
    items = []
    for question in questions:
        cleaned = question.split(": ", 1)[1] if ": " in question else question
        items.append(
            f"""<li><strong>{escape(cleaned)}</strong>
  <div class="response-line">Reviewer response:</div>
</li>"""
        )
    return f"""<section class="section">
  <h2>Reviewer Questions</h2>
  <span class="label">[REVIEWER QUESTIONS \u2014 human judgment required]</span>
  <ol class="questions">
    {''.join(items)}
  </ol>
</section>"""


def _evidence_gaps(critical_flags: list[str]) -> str:
    items = []
    for flag in critical_flags:
        meta = RISK_FLAGS.get(flag)
        if meta is None:
            continue
        docs = meta.get("evidence_required", [])
        items.append(
            f"""<li>
  <strong>Finding:</strong> {escape(flag)}<br>
  <strong>Documents needed:</strong> {escape(_human_list(docs))}
  {_issuance_gap_note(flag)}
</li>"""
        )
    if not items:
        body = "<li class='muted'>No open critical-severity gaps recorded for this project.</li>"
    else:
        body = "".join(items)
    return f"""<section class="section">
  <h2>Evidence Gaps</h2>
  <span class="label">[GAPS \u2014 not yet resolved]</span>
  <ul>
    {body}
  </ul>
</section>"""


def _audit_trail(events: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
    recent_events = _recent_pipeline_events(events)
    rows = _audit_summary_rows(recent_events)
    content_hash = str(snapshot.get("content_hash", ""))
    disclosure = (
        f"Full audit log: {len(events)} events recorded across all pipeline runs. "
        f"Content hash: {content_hash[:16]}..."
    )
    return f"""<section class="section">
  <h2>Audit Trail</h2>
  <span class="label">[AUDIT TRAIL \u2014 most recent pipeline run]</span>
  <table class="audit-table">
    <thead><tr><th>Step</th><th>Events</th><th>Timestamp</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p class="muted">{escape(disclosure)}</p>
</section>"""


def _case_memory(snapshot: dict[str, Any]) -> str:
    return f"""<section class="section">
  <h2>Case Memory</h2>
  <span class="label">[CASE MEMORY \u2014 hash-verified snapshot]</span>
  <p><strong>content_hash:</strong> <span class="hash">{escape(str(snapshot.get("content_hash", "")))}</span></p>
  <p><strong>event_count:</strong> {escape(str(snapshot.get("event_count", "")))}</p>
  <p><strong>snapshot_timestamp:</strong> {escape(str(snapshot.get("snapshot_timestamp", "")))}</p>
</section>"""


def _footer() -> str:
    return f"""<footer>
  <div class="footer-inner">
    <p>{escape(DISCLAIMER_TEXT)}</p>
  </div>
</footer>"""


def _recent_pipeline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    document_events = [event for event in events if event.get("event_type") == "document_ingested"]
    if not document_events:
        return []
    latest_document_time = max(_parse_timestamp(event.get("timestamp", "")) for event in document_events)
    threshold = latest_document_time - timedelta(seconds=5)
    return [
        event for event in events
        if _parse_timestamp(event.get("timestamp", "")) >= threshold
    ]


def _audit_summary_rows(events: list[dict[str, Any]]) -> str:
    row_specs = [
        ("Document ingestion", "document_ingested", _count_events, "documents"),
        ("Chunk extraction", "chunks_created", _count_detail_list("chunk_ids"), "chunks"),
        ("Citation creation", "citations_created", _count_detail_list("citation_ids"), "citations"),
        ("Fact curation", "facts_curated", _count_detail_list("fact_ids"), "facts"),
        ("Evidence cards", "evidence_card_created", _count_events, "cards"),
        ("Conflict detection", "conflict_detected", _count_events, "conflicts"),
        ("Findings flagged", "finding_flagged", _count_events, "findings"),
        ("Memo generated", "memo_generated", _count_events, ""),
        ("Case snapshot", "case_snapshot_taken", _count_events, ""),
    ]
    rows = []
    for step, event_type, counter, noun in row_specs:
        matching = [event for event in events if event.get("event_type") == event_type]
        count = counter(matching)
        label = str(count) if not noun else f"{count} {noun}"
        timestamp = _earliest_timestamp(matching)
        rows.append(
            "<tr>"
            f"<td>{escape(step)}</td>"
            f"<td>{escape(label)}</td>"
            f"<td>{escape(timestamp)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _count_events(events: list[dict[str, Any]]) -> int:
    return len(events)


def _count_detail_list(key: str):
    def count(events: list[dict[str, Any]]) -> int:
        return sum(len(event.get("details", {}).get(key, [])) for event in events)
    return count


def _earliest_timestamp(events: list[dict[str, Any]]) -> str:
    timestamps = sorted(str(event.get("timestamp", "")) for event in events if event.get("timestamp"))
    return timestamps[0] if timestamps else ""


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value)


def _issuance_gap_note(flag: str) -> str:
    if flag != "AR_ISS_GAP_001":
        return ""
    return (
        "<p class='muted'>Note: voluntary cancellations (1,257,195 CERs) "
        "exceed second period balance (374,589 CERs). Serial record verification "
        "required.</p>"
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _field_label(value: str) -> str:
    return FIELD_LABELS.get(value, value.replace("_", " ").title())


def _format_value(value: Any, key: str | None = None) -> str:
    if key == "source_url":
        url = escape(str(value))
        return f'<a href="{url}">{url}</a>'
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in value) + "</ul>"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:,}"
    display_map = {
        "awaiting_issuance_request": "Awaiting issuance request",
        "barrier_analysis": "Barrier analysis",
        "structured_registry_data": "Structured registry data (UNFCCC CDM)",
    }
    if isinstance(value, str) and value in display_map:
        return escape(display_map[value])
    return escape(str(value))


def _human_list(values: list[str]) -> str:
    return ", ".join(value.replace("_", " ") for value in values)


def _parse_args(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(description="Build the Carbon DD v1 review pack.")
    parser.add_argument(
        "project_id",
        nargs="?",
        default=DEFAULT_PROJECT_ID,
        help="Project ID to build the review pack for (default: project_9199)",
    )
    args = parser.parse_args(argv)
    return args.project_id


if __name__ == "__main__":
    main(_parse_args(sys.argv[1:]))
