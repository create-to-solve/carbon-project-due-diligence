from __future__ import annotations
# -*- coding: utf-8 -*-
import html
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from core.audit import (
    AuditLog,
    emit_case_snapshot_taken,
    generate_event_id,
    now_utc_iso,
)
from core.case_memory import build_case_snapshot
from core.evidence import (
    confirmed_proposals_to_facts,
    detect_conflicts,
    load_evidence_cards,
    load_facts,
    load_proposals,
    save_proposals,
    update_proposal_status,
)
from core.extractor import (
    MODEL as EXTRACTOR_MODEL,
    build_proposals,
    extract_facts_from_document,
    generate_finding_narrative,
    get_api_key,
)
from core.ingestion import read_registry
from core.memo import build_memo, memo_to_markdown, reviewer_questions_for
from core.models import AuditEvent, Citation, DocumentChunk, ParsedDocument
from core.paths import ProjectPaths
from core.project_manager import (
    create_project,
    get_project,
    load_project_registry,
)
from domain.project_9199 import PROJECT_9199_FACTS
from domain.risk_flags import claim_topics_for_flag, expected_document_is_held
from domain.rule_router import run_checks_for_project
from domain.rules_cdm import run_all_checks
from scripts.run_ingestion import ingest_paths

ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECT_ID = "project_9199"
PROJECT_ID = DEFAULT_PROJECT_ID
PROJECT_NUMERIC_ID = "9199"
_DEFAULT_PATHS = ProjectPaths(DEFAULT_PROJECT_ID, base_dir=ROOT)
DATA_DIR = _DEFAULT_PATHS.data
RAW_DIR = _DEFAULT_PATHS.raw_documents
PROCESSED_DIR = _DEFAULT_PATHS.processed_documents
REGISTRY_PATH = _DEFAULT_PATHS.document_registry
PROJECT_REGISTRY_PATH = _DEFAULT_PATHS.project_registry
FACTS_PATH = _DEFAULT_PATHS.facts_file
PROPOSALS_PATH = _DEFAULT_PATHS.proposals_file
CARDS_PATH = _DEFAULT_PATHS.evidence_cards_file
AUDIT_PATH = _DEFAULT_PATHS.audit_log
MEMO_PATH = _DEFAULT_PATHS.memo
REVIEW_PACK_PATH = _DEFAULT_PATHS.review_pack
SNAPSHOT_PATH = _DEFAULT_PATHS.case_memory
DISPOSITIONS_PATH = _DEFAULT_PATHS.dispositions
NARRATIVES_PATH = _DEFAULT_PATHS.narratives

PROJECT_LABEL = "Project 9199 \u2014 Forestry Restoration, Colombia"

STATUS_COLORS = {
    "registered": "#475569",
    "deregistered": "#b42318",
    "active": "#16803c",
    "unknown": "#475569",
}

CLAIM_TOPIC_OPTIONS = [
    "baseline_methodology",
    "additionality_demonstration",
    "emission_reductions",
    "crediting_period",
    "validator",
    "verifier",
    "registration",
    "deregistration",
    "issuance",
    "monitoring",
    "permanence",
    "host_party_approval",
    "cancellations",
    "project_identity",
    "issuance_completeness",
    "project_status",
    "monitoring_coverage_period_2",
    "other",
]


def _current_paths() -> ProjectPaths:
    pid = st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    return ProjectPaths(pid, base_dir=ROOT)


def _reviewer_questions_for_project(project_id: str, findings) -> list[str]:
    record = get_project(project_id, str(PROJECT_REGISTRY_PATH)) or {}
    return reviewer_questions_for(record, findings)

BADGE_COLORS = {
    "Critical": "#b42318",
    "High": "#c2410c",
    "Medium": "#a15c00",
    "Low": "#475569",
    "supports": "#16803c",
    "contradicts": "#b42318",
    "needs_more_evidence": "#a15c00",
}

DISCLAIMER = (
    "These findings are produced by deterministic rules applied to structured data. "
    "They indicate areas requiring human investigation, not conclusions."
)


def main() -> None:
    st.set_page_config(
        page_title="Carbon Market Due Diligence v1",
        page_icon="🌱",
        layout="wide",
    )
    _inject_css()
    _init_state()

    registry = _load_project_registry()
    _ensure_valid_project_selection(registry)

    project_id = st.session_state["project_id"]
    paths = ProjectPaths(project_id, base_dir=ROOT)
    project_record = next(
        (p for p in registry if p.get("project_id") == project_id), None
    ) or {}

    facts = _load_fact_records(project_id)
    proposals = _load_proposals_cached(project_id)
    evidence_cards = _load_evidence_cards_cached(project_id)
    registry_records = _load_document_registry()
    documents, chunks, citations = _load_processed_documents_cached(project_id)
    audit_events = _load_audit_events_cached(project_id)
    dispositions = _load_dispositions_cached(project_id)
    narratives = _load_narratives_cached(project_id)
    findings = _compute_findings(project_id, project_record, facts, documents)
    citation_index = {citation.citation_id: citation for citation in citations}
    chunk_index = {chunk.chunk_id: chunk for chunk in chunks}

    _sidebar(registry, project_record, facts, registry_records, documents, findings, audit_events)

    _render_flashes()

    tabs = st.tabs(["Project", "Documents", "AI Proposals", "Facts", "Findings", "Memo", "Audit Trail"])
    with tabs[0]:
        _project_tab(project_id, project_record, findings, documents)
    with tabs[1]:
        _documents_tab(project_id, paths, registry_records, documents, chunks, findings)
    with tabs[2]:
        _ai_proposals_tab(project_id, paths, proposals, documents, chunks, citations, chunk_index)
    with tabs[3]:
        _facts_tab(project_id, paths, facts, evidence_cards, documents, chunks, citations, citation_index, chunk_index)
    with tabs[4]:
        _findings_tab(project_id, project_record, findings, evidence_cards, documents, dispositions, narratives, facts, proposals)
    with tabs[5]:
        _memo_tab(project_id, paths, facts, evidence_cards, findings, audit_events, citation_index, chunk_index)
    with tabs[6]:
        _audit_tab(audit_events)


def _init_state() -> None:
    st.session_state.setdefault("project_id", DEFAULT_PROJECT_ID)
    st.session_state.setdefault("current_project_id", DEFAULT_PROJECT_ID)
    st.session_state.setdefault("new_fact_matches", [])
    st.session_state.setdefault("new_fact_payload", {})
    st.session_state.setdefault("show_new_project_form", False)


def _ensure_valid_project_selection(registry: list[dict]) -> None:
    known_ids = {p.get("project_id") for p in registry}
    current = st.session_state.get("project_id")
    if current in known_ids:
        return
    if DEFAULT_PROJECT_ID in known_ids:
        st.session_state["project_id"] = DEFAULT_PROJECT_ID
    elif registry:
        st.session_state["project_id"] = registry[0].get("project_id", DEFAULT_PROJECT_ID)
    else:
        st.session_state["project_id"] = DEFAULT_PROJECT_ID


def _compute_findings(project_id, project_record, facts, documents):
    methodology_type = (project_record or {}).get("methodology_type", "cdm_ar")
    if project_id == DEFAULT_PROJECT_ID:
        merged = dict(PROJECT_9199_FACTS)
    else:
        merged = {"project_id": project_id}
        if project_record:
            merged["title"] = project_record.get("display_name", project_id)
            merged["host_country"] = project_record.get("host_country")
            merged["methodology"] = project_record.get("methodology")
    for fact in facts:
        key = (fact.get("label") or "").strip().lower().replace(" ", "_")
        if key and key not in merged:
            merged[key] = fact.get("value")
    if not facts and not documents and project_id != DEFAULT_PROJECT_ID:
        return []
    return run_checks_for_project(merged, methodology_type)


def _findings_provisional(facts) -> bool:
    """Findings are provisional until at least one fact is confirmed.

    With zero confirmed facts the deterministic rules report every fact as
    'missing' — even facts the AI has already extracted into pending proposals.
    Those results must not be presented as diligence conclusions.
    """
    return not facts


def _pipeline_step_state(pipeline_ran: bool, facts_confirmed: bool) -> str:
    """Workflow state for the 'Pipeline run' step: done / provisional / todo.

    A run completed before any fact was confirmed is 'provisional', not 'done'.
    """
    if pipeline_ran and not facts_confirmed:
        return "provisional"
    if pipeline_ran:
        return "done"
    return "todo"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #18212f; --muted: #647084; --line: #dbe1ea; --panel: #ffffff;
          --ok: #16803c; --ok-soft: #eaf7ee; --bad: #b42318; --bad-soft: #fdecea;
          --warn: #a15c00; --warn-soft: #fff6e6; --info: #2563eb; --info-soft: #eef3fe;
        }
        /* Typography and rhythm */
        h1, h2, h3, h4 { color: var(--ink); letter-spacing: -0.01em; }
        h2 { font-size: 1.5rem; margin: 0.2rem 0 0.6rem; }
        h3 { font-size: 1.15rem; }
        /* Pills / badges — one consistent shape everywhere */
        .badge {
            display: inline-block; border-radius: 999px; padding: 0.15rem 0.55rem;
            font-size: 0.74rem; font-weight: 700; color: #fff; vertical-align: middle;
            margin: 0.1rem 0.25rem 0.1rem 0;
        }
        .pill {
            display: inline-block; border-radius: 999px; padding: 0.1rem 0.55rem;
            font-size: 0.72rem; font-weight: 700; vertical-align: middle;
            border: 1px solid transparent; margin: 0.05rem 0.15rem 0.05rem 0;
        }
        .pill-ok    { background: var(--ok-soft);   color: var(--ok);   border-color: #a9ddb8; }
        .pill-bad   { background: var(--bad-soft);  color: var(--bad);  border-color: #f0b4ae; }
        .pill-warn  { background: var(--warn-soft); color: var(--warn); border-color: #f3cd89; }
        .pill-muted { background: #eef2f7;          color: #465266;     border-color: var(--line); }
        .source-label {
            display: inline-block; color: #475569; background: #f1f5f9;
            border: 1px solid var(--line); border-radius: 999px; padding: 0.12rem 0.5rem;
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.03em; margin-bottom: 0.6rem;
        }
        .small-muted { color: var(--muted); font-size: 0.86rem; }
        .kv { margin: 0.35rem 0 0.15rem; }
        .kv-label {
            color: var(--muted); font-size: 0.72rem; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.04em;
        }
        .callout {
            border-left: 4px solid var(--info); background: var(--info-soft);
            padding: 0.5rem 0.8rem; border-radius: 6px; margin: 0.5rem 0;
            color: #1f2a3d; font-size: 0.9rem;
        }
        .callout-warn { border-left-color: var(--warn); background: var(--warn-soft); }
        .critical-banner {
            background: #fff1f0; border: 1px solid #f0b4ae; border-left: 6px solid #b42318;
            border-radius: 8px; padding: 1rem; margin: 1rem 0;
        }
        mark { background: #fef08a; padding: 0 0.1rem; }
        div[data-testid="stMetric"] {
            background: var(--panel); border: 1px solid var(--line);
            border-radius: 8px; padding: 0.75rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar(registry, project_record, facts, registry_records, documents, findings, audit_events) -> None:
    options = [p.get("project_id") for p in registry] or [DEFAULT_PROJECT_ID]
    labels = {p.get("project_id"): p.get("display_name", p.get("project_id")) for p in registry}
    current = st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    if current not in options:
        current = options[0]
    project_id = current
    paths = ProjectPaths(project_id, base_dir=ROOT)
    state = _load_pipeline_state(project_id)
    live_counts = _live_counts(project_id, paths, registry_records, facts, findings, state, documents)
    proposals_pending = _count_pending_proposals(paths)

    with st.sidebar:
        st.title("Carbon Market Due Diligence v1")
        st.caption("carbon-dd-v1")
        selected = st.selectbox(
            "Project",
            options,
            index=options.index(current),
            format_func=lambda pid: labels.get(pid, pid),
            key="project_selector",
        )
        if selected != st.session_state.get("project_id"):
            st.session_state["project_id"] = selected
            _clear_data_caches()
            st.rerun()
        if st.button("+ New project"):
            st.session_state["show_new_project_form"] = not st.session_state.get(
                "show_new_project_form", False
            )
        if st.session_state.get("show_new_project_form"):
            _render_new_project_form()
        status = (project_record or {}).get("status", "unknown")
        methodology_type = (project_record or {}).get("methodology_type", "cdm_ar")
        rule_set_label = "CDM A/R" if methodology_type == "cdm_ar" else "Generic"
        st.markdown(
            f"{_badge(status.upper(), STATUS_COLORS.get(status, '#475569'))} "
            f"<span class='pill pill-muted'>Rule set: {html.escape(rule_set_label)}</span>",
            unsafe_allow_html=True,
        )
        st.divider()

        st.subheader("Workflow")
        _render_workflow_progress(live_counts, findings)

        st.divider()
        if live_counts["document_count"] == 0 and live_counts["facts_count"] == 0:
            st.info("No documents yet. Upload documents in the Documents tab to begin.")
        st.metric("Documents", f"{live_counts['document_count']} held")
        st.caption(f"{live_counts['missing_doc_count']} expected not held")
        st.metric("Proposals", f"{proposals_pending} pending")
        st.metric("Facts", f"{live_counts['facts_count']} confirmed")
        st.metric(
            "Findings",
            f"{live_counts['critical_count']} Critical, {live_counts['findings_count']} total",
        )
        st.caption(f"Last pipeline run: {live_counts['last_run_at'] or 'never'}")
        st.caption(f"Audit events: {len(audit_events)}")


def _load_pipeline_state(project_id: str) -> dict:
    path = ProjectPaths(project_id, base_dir=ROOT).pipeline_state
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _live_counts(project_id, paths, registry_records, facts, findings, state, documents=None) -> dict:
    document_count = sum(
        1 for record in registry_records
        if record.get("project_id") == project_id
    )
    if document_count == 0 and state.get("document_count"):
        document_count = state.get("document_count", 0)
    facts_count = len(facts) if facts else state.get("facts_count", 0)
    findings_count = len(findings) if findings else state.get("findings_count", 0)
    critical_count = sum(1 for finding in findings if finding.severity == "Critical")
    if findings_count and not critical_count:
        critical_count = state.get("critical_count", 0)
    missing_docs = [
        row for row in _expected_documents_status(findings, documents or [])
        if row["status"] == "NOT HELD"
    ]
    return {
        "document_count": document_count,
        "facts_count": facts_count,
        "findings_count": findings_count,
        "critical_count": critical_count,
        "missing_doc_count": len(missing_docs),
        "last_run_at": state.get("last_run_at"),
        "memo_exists": paths.memo.exists(),
    }


def _count_pending_proposals(paths: ProjectPaths) -> int:
    if not paths.proposals_file.exists():
        return 0
    try:
        proposals = json.loads(paths.proposals_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return sum(1 for proposal in proposals if proposal.get("status") == "pending")


def _render_workflow_progress(live_counts: dict, findings) -> None:
    project_id = st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    paths = ProjectPaths(project_id, base_dir=ROOT)
    dispositions = _load_dispositions_cached(project_id)
    reviewed = any(
        record.get("disposition") and record.get("disposition") != "Awaiting review"
        for record in dispositions.values()
    )
    facts_confirmed = live_counts["facts_count"] > 0
    pipeline_ran = bool(live_counts.get("last_run_at"))
    documents_held = live_counts["document_count"] > 0
    memo_done = paths.memo.exists()
    # The pipeline may have run before any fact was confirmed. Report that state
    # honestly as provisional rather than as a completed, trustworthy step.
    pipeline_state = _pipeline_step_state(pipeline_ran, facts_confirmed)
    if pipeline_state == "provisional":
        pipeline_icon = "⚠️"
        pipeline_hint = "Provisional — with no confirmed facts the rules report everything as missing"
    elif pipeline_state == "done":
        pipeline_icon = "✅"
        pipeline_hint = None
    else:
        pipeline_icon = "⬜"
        pipeline_hint = "Run after confirming facts"
    steps = [
        ("✅" if documents_held else "⬜", "Documents uploaded",
         None if documents_held else "Upload in Documents tab"),
        ("✅" if facts_confirmed else "⬜", "Facts confirmed",
         None if facts_confirmed else "Confirm proposals in AI Proposals tab"),
        (pipeline_icon, "Pipeline run", pipeline_hint),
        ("✅" if reviewed else "⬜", "Findings reviewed",
         None if reviewed else "Set dispositions in Findings tab"),
        ("✅" if memo_done else "⬜", "Memo downloaded",
         None if memo_done else "Generate in Memo tab"),
    ]
    for icon, label, hint in steps:
        st.markdown(f"{icon} {label}")
        if hint:
            st.markdown(
                f"<span class='small-muted' style='margin-left:1.6rem'>{html.escape(hint)}</span>",
                unsafe_allow_html=True,
            )
    st.caption("Findings become meaningful only after facts are confirmed from proposals.")


def _render_new_project_form() -> None:
    methodology_type_options = {
        "CDM A/R (Afforestation/Reforestation)": (
            "cdm_ar",
            "Use for CDM registered forestry and land-use projects. Applies "
            "CDM-specific rules: additionality, baseline methodology AR-AM*, "
            "validation, registration, deregistration checks.",
        ),
        "Generic (VCS, Gold Standard, other)": (
            "generic",
            "Use for VCS, Gold Standard, Social Carbon, or any non-CDM project. "
            "Applies general carbon market rules: methodology present, validator "
            "identified, additionality demonstrated, crediting period defined.",
        ),
    }
    with st.form("new_project_form"):
        st.markdown("**Create a new project**")
        project_id = st.text_input(
            "Project ID",
            placeholder="project_biochar_001",
            help="Lowercase letters, numbers, underscores only. 3-50 characters.",
        )
        display_name = st.text_input(
            "Display name", placeholder="Biochar Project — Kunnukara, India"
        )
        host_country = st.text_input("Host country")
        methodology = st.text_input("Methodology", placeholder="VM0044 ver. 1.1")
        methodology_type_label = st.selectbox(
            "Methodology type",
            list(methodology_type_options.keys()),
            help=" • ".join(
                f"{label}: {opt[1]}" for label, opt in methodology_type_options.items()
            ),
        )
        st.info("The rule set cannot be changed after project creation. Choose carefully.")
        submitted = st.form_submit_button("Create project")
    if not submitted:
        return
    methodology_type = methodology_type_options[methodology_type_label][0]
    try:
        create_project(
            project_id=project_id.strip(),
            display_name=display_name.strip(),
            host_country=host_country.strip(),
            methodology=methodology.strip(),
            methodology_type=methodology_type,
            registry_path=str(PROJECT_REGISTRY_PATH),
            base_dir=ROOT,
        )
    except ValueError as err:
        st.error(str(err))
        return
    st.success(
        f"Project {project_id} created. Select it from the dropdown to begin."
    )
    st.session_state["show_new_project_form"] = False
    _clear_data_caches()
    st.rerun()


def _project_tab(project_id, project_record, findings, documents) -> None:
    if project_id == DEFAULT_PROJECT_ID:
        header = PROJECT_LABEL
    else:
        header = (project_record or {}).get("display_name", project_id)
    st.header(header)

    if project_id != DEFAULT_PROJECT_ID and not documents:
        st.info(
            f"Project {header} \u2014 no structured data loaded yet. "
            "Upload project documents to begin extraction."
        )
        if project_record:
            rows = [
                {"Field": "Project ID", "Value": project_record.get("project_id", "")},
                {"Field": "Display name", "Value": project_record.get("display_name", "")},
                {"Field": "Host country", "Value": project_record.get("host_country", "")},
                {"Field": "Methodology", "Value": project_record.get("methodology", "")},
                {"Field": "Methodology type", "Value": project_record.get("methodology_type", "")},
                {"Field": "Status", "Value": project_record.get("status", "")},
            ]
            st.dataframe(rows, width="stretch", hide_index=True)
        return

    st.markdown(_source_label("[STRUCTURED DATA \u2014 UNFCCC Registry]"), unsafe_allow_html=True)
    left, right = st.columns([2, 1])
    with left:
        _project_identity_table()
    with right:
        st.subheader("Registry Status")
        facts = PROJECT_9199_FACTS
        c1, c2 = st.columns(2)
        c1.metric("Registration date", facts["registration_date"])
        c2.metric("Deregistration date", facts["deregistration_date"])
        st.metric("Crediting period", f"{facts['crediting_period_start']} to {facts['crediting_period_end']}")
        st.metric("Methodology", facts["methodology"])

    critical = [finding for finding in findings if finding.severity == "Critical"]
    if critical:
        lines = "".join(
            f"<li><strong>{html.escape(f.flag_code)}</strong>: {html.escape(f.description)}</li>"
            for f in critical
        )
        st.markdown(
            f"""
            <div class="critical-banner">
              <strong>{len(critical)} Critical findings identified</strong>
              <ul>{lines}</ul>
              <span class="small-muted">Open the Findings tab to review dispositions and evidence gaps.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _project_identity_table() -> None:
    rows = []
    for key, value in PROJECT_9199_FACTS.items():
        if key == "limitations":
            continue
        rows.append({"Field": _title_key(key), "Value": _display_value(value)})
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("Limitations")
    for limitation in PROJECT_9199_FACTS.get("limitations", []):
        st.markdown(f"<span class='small-muted'>&bull; {html.escape(limitation)}</span>", unsafe_allow_html=True)


def _documents_tab(project_id, paths, registry_records, documents, chunks, findings) -> None:
    st.header("Documents")
    st.subheader("Held Documents")
    st.markdown(_source_label("[EXTRACTED \u2014 parsed evidence base]"), unsafe_allow_html=True)
    if not registry_records:
        st.info(
            "No documents uploaded yet for this project.\n\n"
            "**What to upload:**\n"
            "- Project Description Document (PDD)\n"
            "- Validation report\n"
            "- Monitoring report(s)\n"
            "- Verification report(s)\n"
            "- Any other primary project documents\n\n"
            "Use the uploader below to add PDF files. The system will extract text, "
            "chunk it by page, and run AI fact extraction automatically (if OpenAI key is set)."
        )
    else:
        rows = []
        for record in registry_records:
            rows.append(
                {
                    "Document ID": record.get("document_id", ""),
                    "Title": record.get("title", ""),
                    "Type": record.get("document_type", ""),
                    "Pages": record.get("page_count", 0),
                    "Chunks": record.get("chunk_count", 0),
                    "Parse Status": record.get("parse_status", ""),
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption("Source: data/documents/registry.json")
        for record in registry_records:
            quality = _parse_quality_warning(record)
            if quality:
                st.warning(f"{record.get('title', '')}: {quality}")
    for record in registry_records:
        document_id = record.get("document_id", "")
        doc_chunks = [chunk for chunk in chunks if chunk.document_id == document_id][:5]
        with st.expander(f"View chunks \u2014 {document_id}"):
            st.dataframe(
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "page": chunk.page_number,
                        "heading": chunk.heading or "",
                        "text": _trim(chunk.text, 300),
                    }
                    for chunk in doc_chunks
                ],
                width="stretch",
                hide_index=True,
            )

    st.subheader("Expected Documents")
    st.markdown(_source_label("[DOCUMENT EXISTENCE \u2014 not evidence content]"), unsafe_allow_html=True)
    expected = _expected_documents_status(findings, documents)
    st.dataframe(expected, width="stretch", hide_index=True)
    st.caption(
        "Documents the screening rules expect, with whether one of that kind is held. "
        "HELD means the document exists in the system \u2014 it does NOT mean the related "
        "finding is resolved. Findings are cleared by confirming facts, not by holding documents."
    )

    st.subheader("Add a Document to the Evidence Base")
    st.markdown(
        "<span class='small-muted'>Best results with text-based CDM afforestation/reforestation "
        "PDDs, validation reports, and monitoring reports. Image-only scans may extract poorly.</span>",
        unsafe_allow_html=True,
    )
    upload = st.file_uploader("Upload PDF files", type=["pdf"], accept_multiple_files=False)
    if upload is not None:
        destination = paths.raw_documents / upload.name
        exists = destination.exists()
        st.write(f"Ready to add: {upload.name}")
        if exists:
            st.warning(
                f"A file named {upload.name} is already held for this project. Continuing will replace it."
            )
        button_label = "Replace, ingest, and rerun pipeline" if exists else "Save, ingest, and rerun pipeline"
        if st.button(button_label, type="primary"):
            ingest_error = None
            try:
                with st.spinner(f"Ingesting {upload.name} — parsing pages and re-running the pipeline…"):
                    records = _save_ingest_and_rerun(upload, destination, project_id, paths)
            except Exception as exc:  # never show a traceback in the live flow
                ingest_error = exc
            if ingest_error is not None:
                st.error(
                    "The document could not be ingested. Please check it is a valid, "
                    "text-based PDF and try again."
                )
                st.caption(f"Details: {type(ingest_error).__name__}")
            else:
                for record in records:
                    pages = record.get("page_count", 0) or 0
                    chunks = record.get("chunk_count", 0) or 0
                    warns = record.get("parse_warnings", []) or []
                    _queue_flash(
                        "success",
                        f"Added “{record.get('title', '(untitled)')}” — {pages} page(s), "
                        f"{chunks} chunk(s), parse {record.get('parse_status', '')} "
                        f"({len(warns)} warning(s)). Review extracted facts in the AI Proposals tab.",
                    )
                    quality = _parse_quality_warning(record)
                    if quality:
                        _queue_flash("warning", f"{record.get('title', '')}: {quality}")
                st.rerun()


def _ai_proposals_tab(project_id, paths, proposals, documents, chunks, citations, chunk_index) -> None:
    st.header("AI Proposals")
    st.markdown(
        _source_label("[AI-PROPOSED — candidate facts, not yet confirmed]"),
        unsafe_allow_html=True,
    )
    st.caption(
        "The AI proposes candidate facts from the documents. Nothing becomes a fact "
        "until you confirm it — bulk-confirm is a convenience, never an auto-accept."
    )
    counts = {status: sum(1 for proposal in proposals if proposal.get("status") == status) for status in ["pending", "confirm", "edit", "reject"]}

    cols = st.columns(5)
    cols[0].metric("Total", len(proposals))
    cols[1].metric("Pending", counts["pending"])
    cols[2].metric("Confirmed", counts["confirm"])
    cols[3].metric("Edited", counts["edit"])
    cols[4].metric("Rejected", counts["reject"])

    # --- Fast path: bulk-confirm high-confidence proposals, prominent at the top ---
    high_confidence_pending = [
        proposal for proposal in proposals
        if proposal.get("status") == "pending"
        and float((proposal.get("ai_extracted") or {}).get("confidence") or 0) >= 1.0
    ]
    if high_confidence_pending:
        with st.container(border=True):
            st.markdown("**Fast review**")
            st.write(
                f"{len(high_confidence_pending)} proposal(s) were extracted at confidence = 1.0. "
                "Confirm them together in one click, then review any lower-confidence ones individually below."
            )
            if st.button(
                f"Confirm all high-confidence proposals (confidence = 1.0) — {len(high_confidence_pending)}",
                type="primary",
                use_container_width=True,
            ):
                _bulk_confirm_proposals(project_id, paths, high_confidence_pending)
                remaining = sum(
                    1 for p in proposals
                    if p.get("status") == "pending"
                    and float((p.get("ai_extracted") or {}).get("confidence") or 0) < 1.0
                )
                _queue_flash(
                    "success",
                    f"Confirmed {len(high_confidence_pending)} fact(s). "
                    f"{remaining} lower-confidence proposal(s) remain for individual review. "
                    "Click 'Update facts and rerun pipeline' below to generate findings.",
                )
                _clear_data_caches()
                st.rerun()

    # --- Extraction, with visible progress ---
    if not documents:
        st.info("No documents held yet. Upload documents in the Documents tab, then run AI extraction here.")
        st.button("Run AI extraction on all documents", disabled=True)
        return

    with st.container(border=True):
        st.markdown("**Extract candidate facts from held documents**")
        for document in documents:
            st.markdown(
                f"- {html.escape(document.title)} "
                f"<span class='small-muted'>· {getattr(document, 'page_count', 0) or 0} page(s)</span>",
                unsafe_allow_html=True,
            )
        run_disabled = not get_api_key()
        if run_disabled:
            st.info("Set OPENAI_API_KEY to enable AI extraction. Facts can still be added manually in the Facts tab.")
        if st.button("Run AI extraction on all documents", disabled=run_disabled, type="primary", use_container_width=True):
            progress = st.progress(0.0, text="Preparing extraction…")
            per_doc: list[tuple[str, int, int]] = []

            def _on_document(index, total, document, facts):
                pages = getattr(document, "page_count", 0) or 0
                topics = {(fact.get("claim_topic") or "other") for fact in facts}
                per_doc.append((document.title, len(facts), len(topics)))
                progress.progress(
                    index / max(total, 1),
                    text=f"Reading {document.title} — extracting facts from {pages} page(s). This may take up to a minute.",
                )

            extraction_error = None
            try:
                with st.spinner("Extracting candidate facts — this may take up to a minute…"):
                    new_count = _run_ai_extraction_for_app(
                        project_id, paths, documents, chunks, on_document=_on_document
                    )
            except Exception as exc:  # never surface a traceback in the live flow
                extraction_error = exc

            if extraction_error is not None:
                progress.empty()
                st.error(
                    "Extraction could not be completed. Please retry — check that the OpenAI key "
                    "is set and the document has machine-readable text."
                )
                st.caption(f"Details: {type(extraction_error).__name__}")
            elif new_count == 0:
                progress.empty()
                _queue_flash(
                    "info",
                    "Extraction finished but found no candidate facts. The document may be image-based "
                    "or have little readable text — you can add facts manually in the Facts tab.",
                )
                _clear_data_caches()
                st.rerun()
            else:
                progress.progress(1.0, text="Extraction complete.")
                for title, n_facts, n_topics in per_doc:
                    _queue_flash("success", f"Extracted {n_facts} candidate fact(s) across {n_topics} topic(s) from {title}.")
                _clear_data_caches()
                st.rerun()

    if not proposals:
        st.info("No proposals yet. Run AI extraction above to generate candidate facts for review.")
        return

    topics = sorted({(proposal.get("ai_extracted") or {}).get("claim_topic", "other") for proposal in proposals})
    documents_available = sorted({(proposal.get("ai_extracted") or {}).get("document_id", "") for proposal in proposals if (proposal.get("ai_extracted") or {}).get("document_id")})
    selected_topics = st.multiselect("Filter by claim_topic", topics, default=topics)
    selected_status = st.selectbox("Filter by status", ["all", "pending", "confirm", "edit", "reject"])
    selected_documents = st.multiselect("Filter by document", documents_available, default=documents_available)
    sort_by = st.selectbox("Sort by", ["confidence (desc)", "page number", "claim_topic"])

    visible = _filter_proposals(proposals, selected_topics, selected_status, selected_documents, sort_by)
    for proposal in visible:
        fact = proposal.get("ai_extracted") or {}
        proposal_id = proposal.get("proposal_id", "")
        chunk = chunk_index.get(fact.get("chunk_id", ""))
        status = proposal.get("status", "pending")
        confidence = float(fact.get("confidence") or 0)
        confidence_color = "#16803c" if confidence >= 0.9 else "#a15c00"
        with st.container(border=True):
            st.markdown(
                f"{_badge(str(fact.get('claim_topic', 'other')), _topic_color(str(fact.get('claim_topic', 'other'))))} "
                f"{_badge(f'{confidence:.2f}', confidence_color)} "
                f"{_badge(status, _status_color(status))}",
                unsafe_allow_html=True,
            )
            st.markdown(f"**{fact.get('label', '')}**")
            st.write(f"{fact.get('value', '')} {fact.get('unit') or ''}".strip())
            st.markdown(f"> {fact.get('evidence_quote', '')}")
            st.caption(f"From: {fact.get('document_id', '')}, page {fact.get('page_number', '')}, chunk {fact.get('chunk_id', '')}")
            with st.expander("View full chunk"):
                st.write(chunk.text if chunk else "Chunk text is not currently available.")

            if status == "pending":
                c1, c2, c3 = st.columns(3)
                if c1.button("Confirm", key=f"confirm-{proposal_id}"):
                    _confirm_proposal(proposal)
                    _queue_flash("success", f"Confirmed proposal: {fact.get('label', '')}.")
                    st.rerun()
                if c3.button("Reject", key=f"reject-{proposal_id}"):
                    _reject_proposal(proposal)
                    _queue_flash("info", f"Rejected proposal: {fact.get('label', '')}.")
                    st.rerun()
                with c2.expander("Edit"):
                    with st.form(f"edit-form-{proposal_id}"):
                        label = st.text_input("Label", fact.get("label", ""))
                        value = st.text_input("Value", str(fact.get("value", "")))
                        unit = st.text_input("Unit", fact.get("unit") or "")
                        if st.form_submit_button("Save edit"):
                            edited = {
                                **fact,
                                "label": label,
                                "value": value,
                                "unit": unit or None,
                            }
                            _edit_proposal(proposal, edited)
                            _queue_flash("success", f"Saved edit: {label}.")
                            st.rerun()

    confirmed_ready = [p for p in proposals if p.get("status") in {"confirm", "edit"}]
    st.divider()
    st.subheader("Commit — turn confirmed proposals into facts")
    st.write(
        f"{len(confirmed_ready)} confirmed/edited proposal(s) ready to become facts. "
        "This writes the facts, reruns the deterministic pipeline, and produces findings."
    )
    commit_error = None
    if st.button(
        "Update facts and rerun pipeline",
        type="primary",
        use_container_width=True,
        disabled=not confirmed_ready,
    ):
        try:
            _promote_confirmed_proposals(proposals, project_id, paths)
        except Exception as exc:  # keep the demo calm — no traceback
            commit_error = exc
        if commit_error is not None:
            st.error("Could not update facts and rerun the pipeline. Please retry.")
            st.caption(f"Details: {type(commit_error).__name__}")
        else:
            _queue_flash(
                "success",
                f"Committed {len(confirmed_ready)} fact(s) and reran the pipeline. "
                "Open the Findings tab to see results.",
            )
            _clear_data_caches()
            st.rerun()


def _facts_tab(project_id, paths, facts, evidence_cards, documents, chunks, citations, citation_index, chunk_index) -> None:
    st.header("Facts")
    if not facts:
        st.info(
            "No confirmed facts yet. Confirm proposals in the AI Proposals tab "
            "to populate facts."
        )
    st.subheader("Confirmed Facts")
    for fact in facts:
        citation_id = (fact.get("citation_ids") or [""])[0]
        citation = citation_index.get(citation_id)
        chunk = chunk_index.get(citation.chunk_id) if citation else None
        source = (
            f"[EXTRACTED \u2014 page {citation.page_number}]"
            if citation and chunk
            else "[MANUALLY CURATED \u2014 not yet verified against document]"
        )
        with st.container(border=True):
            st.markdown(f"**{fact.get('label')}**")
            st.markdown(_source_method_badge(str(fact.get("extraction_method", ""))), unsafe_allow_html=True)
            st.write(f"{_display_value(fact.get('value'))} {fact.get('unit') or ''}".strip())
            st.markdown(_source_label(source), unsafe_allow_html=True)
            if fact.get("matched_terms"):
                st.caption("Matched terms: " + ", ".join(fact["matched_terms"]))
            st.caption(f"Citation ID: {citation_id or 'none'}")
            with st.expander("View source chunk"):
                if chunk:
                    st.markdown(
                        _highlight_terms(chunk.text, fact.get("matched_terms") or fact.get("search_terms") or []),
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No matching source chunk is currently held.")

    st.subheader("Propose a New Fact")
    st.markdown(_source_label("Fact proposals require human confirmation before they affect findings."), unsafe_allow_html=True)
    document_ids = [doc.document_id for doc in documents]
    with st.form("new_fact_form"):
        label = st.text_input("Fact label")
        value = st.text_input("Value")
        unit = st.text_input("Unit (optional)")
        notes = st.text_input("Notes")
        if document_ids:
            source_document = st.selectbox("Source document", document_ids)
        else:
            source_document = ""
            st.caption("Upload documents to enable fact proposals.")
        search_clicked = st.form_submit_button(
            "Search document for this fact", disabled=not document_ids
        )
    if search_clicked:
        terms = [term for term in [label, value] if term.strip()]
        st.session_state.new_fact_payload = {
            "label": label,
            "value": value,
            "unit": unit or None,
            "notes": notes,
            "source_document_id": source_document,
            "search_terms": terms,
        }
        st.session_state.new_fact_matches = _top_chunk_matches(terms, chunks, source_document)[:3]
    if st.session_state.new_fact_matches:
        choices = {
            f"{match['chunk'].chunk_id} \u2014 page {match['chunk'].page_number} \u2014 score {match['score']}": match
            for match in st.session_state.new_fact_matches
        }
        selected = st.selectbox("Select source chunk to cite", list(choices))
        for label_text, match in choices.items():
            with st.expander(label_text):
                st.markdown(_highlight_terms(match["chunk"].text, match["matched_terms"]), unsafe_allow_html=True)
        if st.button("Save proposed fact"):
            _save_new_fact(st.session_state.new_fact_payload, choices[selected], citations, paths)
            st.success("Fact saved as manually proposed evidence.")
            _clear_data_caches()
            st.rerun()

    _evidence_card_authoring_section(project_id, paths, facts, evidence_cards)


def _evidence_card_authoring_section(project_id, paths, facts, evidence_cards) -> None:
    fact_label_by_id = {fact.get("fact_id"): fact.get("label", "") for fact in facts}
    fact_options = list(fact_label_by_id.keys())
    with st.expander("Add evidence card"):
        with st.form("new_evidence_card_form", clear_on_submit=True):
            claim = st.text_area(
                "Claim",
                placeholder="The project applies VM0044 ver. 1.1 as the baseline methodology.",
                help="State the specific claim this card supports or contradicts.",
            )
            claim_topic = st.selectbox(
                "Claim topic",
                CLAIM_TOPIC_OPTIONS,
            )
            evidence_role = st.selectbox(
                "Evidence role",
                ["supports", "contradicts", "needs_more_evidence"],
            )
            reviewer_note = st.text_input(
                "Reviewer note (optional)",
                placeholder="Source: PDD section 3.2",
            )
            linked_facts = st.multiselect(
                "Link to facts",
                fact_options,
                format_func=lambda fid: f"{fid} — {fact_label_by_id.get(fid, '')}",
                help="Select facts that support this card's claim",
            )
            submitted = st.form_submit_button("Save evidence card")
        if submitted:
            if not claim.strip():
                st.error("Claim cannot be empty.")
            else:
                _save_evidence_card(
                    project_id=project_id,
                    paths=paths,
                    claim=claim.strip(),
                    claim_topic=claim_topic,
                    evidence_role=evidence_role,
                    reviewer_note=reviewer_note.strip(),
                    fact_ids=linked_facts,
                )
                st.success("Evidence card saved.")
                _clear_data_caches()
                st.rerun()

    st.markdown(_source_label("[EVIDENCE CARDS — human authored]"), unsafe_allow_html=True)
    if not evidence_cards:
        st.info(
            "No evidence cards yet. Use the form above to add cards after confirming facts."
        )
        return
    for card in evidence_cards:
        role = getattr(card, "evidence_role", "")
        topic = getattr(card, "claim_topic", "")
        claim = getattr(card, "claim", "")
        note = getattr(card, "reviewer_note", "")
        fact_ids = getattr(card, "fact_ids", []) or []
        created_at = getattr(card, "created_at", "")
        role_color = BADGE_COLORS.get(role, "#475569")
        with st.container(border=True):
            st.markdown(f"**{html.escape(str(claim))}**")
            st.markdown(
                f"{_badge(str(topic), _topic_color(str(topic)))} "
                f"{_badge(str(role), role_color)}",
                unsafe_allow_html=True,
            )
            if note:
                st.markdown(
                    f"<span class='small-muted'>Reviewer note: {html.escape(str(note))}</span>",
                    unsafe_allow_html=True,
                )
            if fact_ids:
                linked_labels = [
                    fact_label_by_id.get(fid, fid) for fid in fact_ids if fid
                ]
                st.caption("Linked facts: " + ", ".join(linked_labels))
            if created_at:
                st.caption(f"Created at: {_format_iso_timestamp(created_at)}")


def _save_evidence_card(
    project_id: str,
    paths: ProjectPaths,
    claim: str,
    claim_topic: str,
    evidence_role: str,
    reviewer_note: str,
    fact_ids: list[str],
) -> None:
    paths.evidence_cards_file.parent.mkdir(parents=True, exist_ok=True)
    if paths.evidence_cards_file.exists():
        cards = json.loads(paths.evidence_cards_file.read_text(encoding="utf-8"))
    else:
        cards = []
    card_id = f"card-{project_id}-{uuid.uuid4().hex[:6]}"
    new_card = {
        "card_id": card_id,
        "claim": claim,
        "claim_topic": claim_topic,
        "fact_ids": list(fact_ids),
        "citation_ids": [],
        "evidence_role": evidence_role,
        "review_status": "human_authored",
        "reviewer_note": reviewer_note,
        "conflicts_with": [],
        "subject_id": project_id,
        "subject_type": "project",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    cards.append(new_card)
    paths.evidence_cards_file.write_text(
        json.dumps(cards, indent=2, sort_keys=True), encoding="utf-8"
    )
    log = AuditLog(str(paths.audit_log))
    log.write(
        AuditEvent(
            event_id=generate_event_id(),
            event_type="evidence_card_created",
            subject_id=card_id,
            subject_type="evidence",
            timestamp=now_utc_iso(),
            actor="human",
            lab_origin="carbon-dd-v1",
            summary=f"Evidence card {card_id} created for {claim_topic}",
            details={
                "card_id": card_id,
                "claim_topic": claim_topic,
                "evidence_role": evidence_role,
                "fact_ids": list(fact_ids),
            },
        )
    )


def _format_iso_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(value)


def _findings_tab(project_id, project_record, findings, evidence_cards, documents, dispositions, narratives, facts, proposals) -> None:
    st.header("Findings")
    methodology_type = (project_record or {}).get("methodology_type", "cdm_ar")
    rule_set_label = "CDM A/R" if methodology_type == "cdm_ar" else "Generic"

    pending_proposals = [p for p in (proposals or []) if p.get("status") == "pending"]

    # Zero confirmed facts: the rules would fire "missing X" for everything, which
    # misleads a reviewer who has proposals naming those very facts. Show a state
    # instead of presenting provisional findings as diligence conclusions.
    if _findings_provisional(facts):
        with st.container(border=True):
            st.subheader("Findings pending fact confirmation")
            if pending_proposals:
                st.markdown(
                    f"**{len(pending_proposals)} AI proposal(s)** are awaiting your review. "
                    "Findings are generated from **confirmed** facts, so none are shown yet."
                )
                st.markdown(
                    "**Next step:** open the **AI Proposals** tab, confirm the high-confidence "
                    "proposals, then click *Update facts and rerun pipeline*."
                )
            else:
                st.markdown(
                    "No confirmed facts and no pending proposals yet. Upload documents in the "
                    "**Documents** tab and run AI extraction in **AI Proposals**, then confirm facts."
                )
            st.caption(
                "Findings are withheld until at least one fact is confirmed. Run before "
                "confirmation, the rules would report every fact as 'missing' — even ones the AI "
                "has already extracted. This state is intentional, not an error."
            )
        return

    if not findings:
        st.info(
            "No findings yet. Facts must be confirmed before the rule engine can run.\n\n"
            f"Rule set that will apply: **{rule_set_label}** (methodology_type = `{methodology_type}`)."
        )
        return
    counts = {severity: sum(1 for finding in findings if finding.severity == severity) for severity in ["Critical", "High", "Medium", "Low"]}
    st.markdown(
        _source_label(f"[SYSTEM-GENERATED \u2014 {rule_set_label} rule set \u2014 requires human review]"),
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    cols[0].metric("Total", len(findings))
    for index, severity in enumerate(["Critical", "High", "Medium", "Low"], start=1):
        cols[index].metric(severity, counts[severity])
    if counts["Critical"]:
        st.error(f"{counts['Critical']} critical finding(s) require attention before any credit transaction.")
    elif counts["High"]:
        st.warning(f"{counts['High']} high-severity finding(s) to review.")
    else:
        st.info("Review each finding below and set a reviewer disposition.")

    cards_by_id = {card.card_id: card for card in evidence_cards}
    held_types = _held_document_types(documents)
    pending_topic_counts: dict[str, int] = {}
    for proposal in pending_proposals:
        topic = (proposal.get("ai_extracted") or {}).get("claim_topic")
        if topic:
            pending_topic_counts[topic] = pending_topic_counts.get(topic, 0) + 1
    api_key_set = bool(get_api_key())
    for finding in findings:
        latest = dispositions.get(finding.finding_id, {})
        with st.container(border=True):
            plain_title = _finding_plain_title(finding)
            st.markdown(
                f"{_severity_badge(finding.severity)} <b>{html.escape(plain_title)}</b> "
                f"<span class='small-muted'>&middot; {html.escape(finding.flag_code)}</span>",
                unsafe_allow_html=True,
            )
            st.write(finding.description)
            st.markdown(
                "<div class='kv'><span class='kv-label'>What's missing</span></div>"
                f"<div>{html.escape(finding.evidence_gap)}</div>",
                unsafe_allow_html=True,
            )
            unconfirmed = sum(
                pending_topic_counts.get(topic, 0)
                for topic in claim_topics_for_flag(finding.flag_code)
            )
            if unconfirmed:
                st.markdown(
                    f"<div class='callout'>{unconfirmed} unconfirmed proposal(s) may address this "
                    "&mdash; review in the <b>AI Proposals</b> tab.</div>",
                    unsafe_allow_html=True,
                )
            doc_bits = []
            for required in finding.required_documents:
                name = html.escape(required.replace("_", " "))
                if expected_document_is_held(required, held_types):
                    doc_bits.append(f"{name} {_pill('HELD', 'ok')} <span class='small-muted'>contents not verified</span>")
                else:
                    doc_bits.append(f"{name} {_pill('NOT HELD', 'bad')}")
            docs_html = "".join(f"<div style='margin:3px 0'>{bit}</div>" for bit in doc_bits)
            st.markdown(
                f"<div class='kv'><span class='kv-label'>Documents needed</span></div>{docs_html}",
                unsafe_allow_html=True,
            )
            linked_cards = [cards_by_id.get(card_id) for card_id in finding.evidence_card_ids]
            linked_cards = [card for card in linked_cards if card]
            if linked_cards:
                cards_html = "".join(
                    f"<div style='margin:3px 0'><span class='small-muted'>{html.escape(card.claim)}</span> "
                    f"{_badge(card.evidence_role, BADGE_COLORS.get(card.evidence_role, '#475569'))}</div>"
                    for card in linked_cards
                )
                st.markdown(
                    f"<div class='kv'><span class='kv-label'>Evidence cards</span></div>{cards_html}",
                    unsafe_allow_html=True,
                )

            if finding.flag_code in narratives:
                with st.expander("AI analysis"):
                    st.write(narratives[finding.flag_code])
                    st.markdown(
                        "<span class='small-muted'>[AI-DRAFT — grounded in confirmed evidence, requires human review]</span>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Regenerate narrative",
                        key=f"regen-narr-{finding.finding_id}",
                        disabled=not api_key_set,
                    ):
                        _regenerate_narrative_for_finding(finding, evidence_cards)
                        _regenerate_memo_with_narratives(project_id, evidence_cards, findings)
                        _queue_flash("success", f"Regenerated AI analysis for {finding.flag_code} and updated the memo.")
                        _clear_data_caches()
                        st.rerun()

            st.markdown("<div class='kv'><span class='kv-label'>Reviewer decision</span></div>", unsafe_allow_html=True)
            disposition_options = ["Awaiting review", "Accept", "Needs verification", "Dismiss"]
            dcol, _spacer = st.columns([1, 2])
            disposition = dcol.selectbox(
                "Disposition",
                disposition_options,
                index=disposition_options.index(latest.get("disposition", "Awaiting review")),
                key=f"disp-{finding.finding_id}",
                label_visibility="collapsed",
            )
            note = st.text_area(
                "Reviewer note",
                latest.get("note", ""),
                key=f"note-{finding.finding_id}",
                placeholder="Optional note for the record…",
            )
            if st.button("Save disposition", key=f"save-{finding.finding_id}"):
                _append_disposition(finding.finding_id, disposition, note, project_id)
                _queue_flash("success", f"Saved disposition for {finding.flag_code}: {disposition}.")
                st.rerun()
    st.caption(DISCLAIMER)


def _memo_tab(project_id, paths, facts, evidence_cards, findings, audit_events, citation_index, chunk_index) -> None:
    st.header("Reviewer Memo")
    st.markdown(
        _source_label("[REVIEWER MEMO — cited, hash-verified, requires human verification]"),
        unsafe_allow_html=True,
    )
    st.caption(
        "A professional due-diligence memo generated from the confirmed evidence base. "
        "System-generated and cited — it records what is known, missing, and uncertain; it does not make the judgment."
    )
    if not paths.memo.exists():
        st.info("No memo generated yet. Confirm facts and run the pipeline, then generate the memo below.")
    memo_text = paths.memo.read_text(encoding="utf-8") if paths.memo.exists() else ""
    metadata = _memo_metadata(memo_text, audit_events)
    cols = st.columns(4)
    cols[0].metric("Memo ID", metadata["memo_id"])
    cols[1].metric("Generated", metadata["generated_at"])
    cols[2].metric("Content hash", metadata["content_hash"][:12] or "—")
    cols[3].metric("Audit events", len(audit_events))

    if st.button(
        "Generate memo and review pack",
        type="primary",
        use_container_width=True,
        key="generate_memo_and_pack",
    ):
        with st.spinner("Generating..."):
            _generate_memo_and_pack(project_id, paths, evidence_cards, findings)
        st.success("Done. Download below.")
        _clear_data_caches()
        memo_text = paths.memo.read_text(encoding="utf-8") if paths.memo.exists() else ""

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Download memo (Markdown)",
        memo_text,
        f"{project_id}_memo.md",
        "text/markdown",
        use_container_width=True,
    )
    if paths.review_pack.exists():
        download_cols[1].download_button(
            "Download review pack (HTML)",
            paths.review_pack.read_bytes(),
            f"{project_id}_review_pack.html",
            "text/html",
            use_container_width=True,
        )
    else:
        download_cols[1].caption("Review pack not generated yet.")

    with st.expander("Advanced options"):
        c1, c2 = st.columns(2)
        if c1.button("Regenerate memo only"):
            narratives = _load_narratives() or None
            memo_facts = dict(PROJECT_9199_FACTS) if project_id == DEFAULT_PROJECT_ID else {"project_id": project_id}
            memo = build_memo(
                memo_facts.get("project_id", project_id),
                memo_facts,
                evidence_cards,
                findings,
                AuditLog(str(paths.audit_log)),
                narratives,
                reviewer_questions=_reviewer_questions_for_project(project_id, findings),
            )
            paths.memo.parent.mkdir(parents=True, exist_ok=True)
            paths.memo.write_text(memo_to_markdown(memo), encoding="utf-8")
            _clear_data_caches()
            st.success("Memo regenerated.")
            st.rerun()
        if c2.button("Build review pack only"):
            output = _run_script("scripts/build_review_pack.py", project_id)
            st.success(output or "Review pack built.")

    st.divider()
    sections = _parse_memo_sections(memo_text)
    if not sections:
        st.caption("The memo body will appear here once generated.")
    for title, body in sections:
        st.markdown(f"#### {html.escape(title)}")
        first_line, rest = _split_source_line(body)
        if first_line:
            st.markdown(_source_label(first_line), unsafe_allow_html=True)
        st.markdown(rest)
        if "Evidence summary" in title:
            for citation_id in _citation_ids_from_text(rest):
                citation = citation_index.get(citation_id)
                chunk = chunk_index.get(citation.chunk_id) if citation else None
                with st.expander(f"Source chunk \u2014 {citation_id}"):
                    if chunk:
                        st.caption(f"Page {citation.page_number} | Chunk {chunk.chunk_id}")
                        st.write(chunk.text)
                    else:
                        st.info("Citation chunk is not currently held.")
        st.divider()


def _audit_tab(audit_events) -> None:
    st.header("Audit Trail")
    if not audit_events:
        st.info("No events yet for this project.")
        return
    st.markdown(_source_label("[AUDIT TRAIL \u2014 append-only]"), unsafe_allow_html=True)
    timestamps = sorted(event.get("timestamp", "") for event in audit_events if event.get("timestamp"))
    subjects = sorted({event.get("subject_id", "") for event in audit_events})
    c1, c2, c3 = st.columns(3)
    c1.metric("Total events", len(audit_events))
    c2.metric("Date range", f"{timestamps[0]} -> {timestamps[-1]}" if timestamps else "none")
    c3.metric("Subjects covered", len(subjects))

    event_types = ["All"] + sorted({event.get("event_type", "") for event in audit_events})
    selected_type = st.selectbox("Filter by event_type", event_types)
    subject_filter = st.text_input("Filter by subject_id")
    rows = []
    for event in sorted(audit_events, key=lambda item: item.get("timestamp", ""), reverse=True):
        if selected_type != "All" and event.get("event_type") != selected_type:
            continue
        if subject_filter and subject_filter.lower() not in event.get("subject_id", "").lower():
            continue
        event_type = event.get("event_type", "")
        color = {
            "document_ingested": "#2563eb",
            "finding_flagged": "#b42318",
            "memo_generated": "#16803c",
            "case_snapshot_taken": "#7e22ce",
            "review_completed": "#0f766e",
        }.get(event_type, "#475569")
        rows.append(
            {
                "timestamp": event.get("timestamp", ""),
                "event_type": f"<span style='color:{color};font-weight:700'>{html.escape(event_type)}</span>",
                "subject_id": html.escape(event.get("subject_id", "")),
                "summary": html.escape(event.get("summary", "")),
            }
        )
    if rows:
        st.markdown(_html_table(rows), unsafe_allow_html=True)
    else:
        st.info("No audit events match the current filters.")

    st.subheader("Case Memory")
    project_id = st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    paths = ProjectPaths(project_id, base_dir=ROOT)
    snapshot = _load_snapshot(project_id)
    st.code(snapshot.get("content_hash", "No snapshot"))
    st.write(f"event_count: {snapshot.get('event_count', 'unknown')}")
    st.write(f"snapshot_timestamp: {snapshot.get('snapshot_timestamp', 'unknown')}")
    if st.button("Take new snapshot"):
        snap_subject = f"project-{project_id}"
        snapshot = build_case_snapshot(
            AuditLog(str(paths.audit_log)),
            project_id=project_id,
            subject_id=snap_subject,
            case_id=f"case-{snap_subject}",
            output_path=str(paths.case_memory),
        )
        emit_case_snapshot_taken(
            AuditLog(str(paths.audit_log)),
            project_id,
            snapshot.case_id,
            snapshot.content_hash,
            snapshot.event_count,
        )
        _clear_data_caches()
        st.success("New hash-verified case snapshot taken.")
        st.rerun()


@st.cache_data(show_spinner=False)
def _load_project_registry() -> list[dict[str, Any]]:
    return load_project_registry(str(PROJECT_REGISTRY_PATH))


@st.cache_data(show_spinner=False)
def _load_fact_records(project_id: str) -> list[dict[str, Any]]:
    path = ProjectPaths(project_id, base_dir=ROOT).facts_file
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def _load_proposals_cached(project_id: str) -> list[dict[str, Any]]:
    path = ProjectPaths(project_id, base_dir=ROOT).proposals_file
    return load_proposals(str(path))


@st.cache_data(show_spinner=False)
def _load_evidence_cards_cached(project_id: str):
    path = ProjectPaths(project_id, base_dir=ROOT).evidence_cards_file
    if not path.exists():
        return []
    return load_evidence_cards(str(path))


@st.cache_data(show_spinner=False)
def _load_audit_events_cached(project_id: str) -> list[dict[str, Any]]:
    path = ProjectPaths(project_id, base_dir=ROOT).audit_log
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@st.cache_data(show_spinner=False)
def _load_snapshot(project_id: str) -> dict[str, Any]:
    path = ProjectPaths(project_id, base_dir=ROOT).case_memory
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def _load_document_registry() -> list[dict[str, Any]]:
    return read_registry(REGISTRY_PATH, project_id=st.session_state.get("project_id", DEFAULT_PROJECT_ID))


@st.cache_data(show_spinner=False)
def _load_processed_documents_cached(project_id: str) -> tuple[list[ParsedDocument], list[DocumentChunk], list[Citation]]:
    processed_dir = ProjectPaths(project_id, base_dir=ROOT).processed_documents
    documents: list[ParsedDocument] = []
    chunks: list[DocumentChunk] = []
    citations: list[Citation] = []
    if not processed_dir.exists():
        return documents, chunks, citations
    for path in sorted(processed_dir.glob("*_parsed_document.json")):
        document = ParsedDocument(**json.loads(path.read_text(encoding="utf-8")))
        documents.append(document)
        chunk_path = processed_dir / f"{document.document_id}_chunks.json"
        citation_path = processed_dir / f"{document.document_id}_citations.json"
        if chunk_path.exists():
            chunks.extend(DocumentChunk(**item) for item in json.loads(chunk_path.read_text(encoding="utf-8")))
        if citation_path.exists():
            citations.extend(Citation(**item) for item in json.loads(citation_path.read_text(encoding="utf-8")))
    return documents, chunks, citations


def _load_processed_documents() -> tuple[list[ParsedDocument], list[DocumentChunk], list[Citation]]:
    return _load_processed_documents_cached(
        st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    )


@st.cache_data(show_spinner=False)
def _load_narratives_cached(project_id: str) -> dict[str, str]:
    path = ProjectPaths(project_id, base_dir=ROOT).narratives
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    narratives = payload.get("narratives", {})
    return {str(k): str(v) for k, v in narratives.items()}


def _load_narratives() -> dict[str, str]:
    return _load_narratives_cached(
        st.session_state.get("project_id", DEFAULT_PROJECT_ID)
    )


@st.cache_data(show_spinner=False)
def _load_dispositions_cached(project_id: str) -> dict[str, dict[str, Any]]:
    path = ProjectPaths(project_id, base_dir=ROOT).dispositions
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    latest = {}
    for record in records:
        latest[record["finding_id"]] = record
    return latest


def _held_document_types(documents) -> set[str]:
    return {document.document_type for document in documents}


def _expected_documents_status(findings, documents) -> list[dict[str, str]]:
    """All expected documents with an honest held/not-held status.

    'Held' proves a document of that kind exists; it never resolves a finding,
    which is driven by confirmed facts (see EXPECTED_TO_HELD_TYPE docstring).
    """
    held_types = _held_document_types(documents)
    rows = []
    seen = set()
    for finding in findings:
        for doc in finding.required_documents:
            if doc in seen:
                continue
            seen.add(doc)
            held = expected_document_is_held(doc, held_types)
            rows.append(
                {
                    "document": doc.replace("_", " "),
                    "status": "HELD (contents not verified)" if held else "NOT HELD",
                    "why expected": finding.evidence_gap,
                    "related finding": finding.flag_code,
                }
            )
    return rows


def _top_chunk_matches(terms: list[str], chunks: list[DocumentChunk], document_id: str) -> list[dict[str, Any]]:
    normalized = [term.lower() for term in terms if term.strip()]
    matches = []
    for chunk in chunks:
        if chunk.document_id != document_id:
            continue
        text = chunk.text.lower()
        matched = [term for term in normalized if term in text]
        if matched:
            matches.append({"chunk": chunk, "score": len(matched), "matched_terms": matched})
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def _run_ai_extraction_for_app(
    project_id: str,
    paths: ProjectPaths,
    documents: list[ParsedDocument],
    chunks: list[DocumentChunk],
    on_document=None,
) -> int:
    all_proposals = load_proposals(str(paths.proposals_file))
    new_count = 0
    context = _project_context_dict(project_id)
    total = len(documents)
    for index, document in enumerate(documents, start=1):
        doc_chunks = [chunk for chunk in chunks if chunk.document_id == document.document_id]
        facts = extract_facts_from_document(document, doc_chunks, context)
        proposals = build_proposals(facts, project_id)
        all_proposals.extend(proposals)
        new_count += len(proposals)
        if on_document is not None:
            # UI progress only — does not affect extraction results.
            on_document(index, total, document, facts)
    save_proposals(all_proposals, str(paths.proposals_file))
    return new_count


def _project_context_dict(project_id: str) -> dict:
    if project_id == DEFAULT_PROJECT_ID:
        return dict(PROJECT_9199_FACTS)
    record = get_project(project_id, str(PROJECT_REGISTRY_PATH)) or {}
    return {
        "project_id": project_id,
        "title": record.get("display_name", project_id),
        "host_country": record.get("host_country"),
        "methodology": record.get("methodology"),
    }


def _filter_proposals(
    proposals: list[dict[str, Any]],
    topics: list[str],
    status: str,
    documents: list[str],
    sort_by: str,
) -> list[dict[str, Any]]:
    filtered = []
    for proposal in proposals:
        fact = proposal.get("ai_extracted") or {}
        if topics and fact.get("claim_topic", "other") not in topics:
            continue
        if status != "all" and proposal.get("status") != status:
            continue
        if documents and fact.get("document_id") not in documents:
            continue
        filtered.append(proposal)
    if sort_by == "confidence (desc)":
        return sorted(filtered, key=lambda p: float((p.get("ai_extracted") or {}).get("confidence") or 0), reverse=True)
    if sort_by == "page number":
        return sorted(filtered, key=lambda p: int((p.get("ai_extracted") or {}).get("page_number") or 0))
    return sorted(filtered, key=lambda p: str((p.get("ai_extracted") or {}).get("claim_topic", "")))


def _bulk_confirm_proposals(project_id: str, paths: ProjectPaths, targets: list[dict[str, Any]]) -> None:
    from core.audit import emit_proposal_confirmed
    proposals = load_proposals(str(paths.proposals_file))
    target_ids = {proposal.get("proposal_id") for proposal in targets}
    log = AuditLog(str(paths.audit_log))
    updated = proposals
    for proposal in proposals:
        if proposal.get("proposal_id") not in target_ids:
            continue
        if proposal.get("status") != "pending":
            continue
        updated = update_proposal_status(updated, proposal["proposal_id"], "confirm")
        fact = proposal.get("ai_extracted") or {}
        emit_proposal_confirmed(
            log,
            proposal["proposal_id"],
            str(fact.get("label", "")),
            str(fact.get("value", "")),
            str(fact.get("claim_topic", "")),
        )
    save_proposals(updated, str(paths.proposals_file))


def _confirm_proposal(proposal: dict[str, Any]) -> None:
    paths = _current_paths()
    proposals = load_proposals(str(paths.proposals_file))
    fact = proposal.get("ai_extracted") or {}
    save_proposals(
        update_proposal_status(proposals, proposal["proposal_id"], "confirm"),
        str(paths.proposals_file),
    )
    from core.audit import emit_proposal_confirmed
    emit_proposal_confirmed(
        AuditLog(str(paths.audit_log)),
        proposal["proposal_id"],
        str(fact.get("label", "")),
        str(fact.get("value", "")),
        str(fact.get("claim_topic", "")),
    )
    _clear_data_caches()


def _edit_proposal(proposal: dict[str, Any], edited: dict[str, Any]) -> None:
    paths = _current_paths()
    proposals = load_proposals(str(paths.proposals_file))
    original = proposal.get("ai_extracted") or {}
    save_proposals(
        update_proposal_status(proposals, proposal["proposal_id"], "edit", human_edit=edited),
        str(paths.proposals_file),
    )
    from core.audit import emit_proposal_edited
    emit_proposal_edited(
        AuditLog(str(paths.audit_log)),
        proposal["proposal_id"],
        str(original.get("label", "")),
        str(edited.get("label", "")),
    )
    _clear_data_caches()


def _reject_proposal(proposal: dict[str, Any]) -> None:
    paths = _current_paths()
    proposals = load_proposals(str(paths.proposals_file))
    fact = proposal.get("ai_extracted") or {}
    save_proposals(
        update_proposal_status(proposals, proposal["proposal_id"], "reject", audit_note="human_rejected"),
        str(paths.proposals_file),
    )
    from core.audit import emit_proposal_rejected
    emit_proposal_rejected(
        AuditLog(str(paths.audit_log)),
        proposal["proposal_id"],
        str(fact.get("label", "")),
        str(fact.get("claim_topic", "")),
    )
    _clear_data_caches()


def _promote_confirmed_proposals(proposals: list[dict[str, Any]], project_id: str, paths: ProjectPaths) -> str:
    if paths.facts_file.exists():
        existing = json.loads(paths.facts_file.read_text(encoding="utf-8"))
    else:
        existing = []
    existing_ids = {fact.get("fact_id") for fact in existing}
    _, _, citations = _load_processed_documents_cached(project_id)
    citations_by_chunk = {citation.chunk_id: citation.citation_id for citation in citations}
    new_facts = confirmed_proposals_to_facts(proposals)
    appended = []
    for fact in new_facts:
        if fact.get("fact_id") in existing_ids:
            continue
        chunk_id = fact.get("chunk_id")
        if chunk_id and not fact.get("citation_ids"):
            citation_id = citations_by_chunk.get(chunk_id)
            if citation_id:
                fact["citation_ids"] = [citation_id]
        appended.append(fact)
    paths.facts_file.parent.mkdir(parents=True, exist_ok=True)
    paths.facts_file.write_text(json.dumps(existing + appended, indent=2, sort_keys=True), encoding="utf-8")
    confirmed_count = sum(1 for proposal in proposals if proposal.get("status") == "confirm")
    edited_count = sum(1 for proposal in proposals if proposal.get("status") == "edit")
    total_facts = len(existing) + len(appended)
    from core.audit import emit_facts_updated_from_proposals
    emit_facts_updated_from_proposals(
        AuditLog(str(paths.audit_log)),
        project_id,
        confirmed_count,
        edited_count,
        total_facts,
    )
    pipeline_result = _run_script("scripts/run_pipeline.py", project_id)
    _clear_data_caches()
    return pipeline_result


def _save_new_fact(payload: dict[str, Any], match: dict[str, Any], citations: list[Citation], paths: ProjectPaths) -> None:
    records = json.loads(paths.facts_file.read_text(encoding="utf-8")) if paths.facts_file.exists() else []
    chunk = match["chunk"]
    citation = next((item for item in citations if item.chunk_id == chunk.chunk_id), None)
    next_id = len(records) + 1
    records.append(
        {
            "fact_id": f"fact-{paths.project_id}-{next_id:03d}",
            "label": payload["label"],
            "value": payload["value"],
            "unit": payload["unit"],
            "source_document_id": payload["source_document_id"],
            "citation_ids": [citation.citation_id] if citation else [],
            "extraction_method": "human_proposed",
            "confidence": 0.0,
            "notes": payload["notes"],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "search_terms": payload["search_terms"],
            "matched_terms": match["matched_terms"],
        }
    )
    paths.facts_file.parent.mkdir(parents=True, exist_ok=True)
    paths.facts_file.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")


def _save_ingest_and_rerun(upload, destination: Path, project_id: str, paths: ProjectPaths) -> list[dict]:
    paths.raw_documents.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(upload.getbuffer())
    records = ingest_paths([destination], paths.processed_documents, project_id, paths.document_registry)
    _run_script("scripts/run_pipeline.py", project_id)
    _clear_data_caches()
    return records


def _parse_quality_warning(record: dict) -> str | None:
    """Honest, calm note when a document parsed poorly (likely image-based)."""
    pages = record.get("page_count", 0) or 0
    chunks = record.get("chunk_count", 0) or 0
    empty = max(pages - chunks, 0) if pages else 0
    if pages and empty and empty / pages > 0.2:
        return (
            f"This document appears to be image-based or has limited extractable text "
            f"({empty} of {pages} pages empty). Fact extraction may be incomplete."
        )
    return None


def _generate_memo_and_pack(project_id: str, paths: ProjectPaths, evidence_cards, findings) -> None:
    if get_api_key() and findings:
        _regenerate_all_narratives(project_id, paths, evidence_cards, findings)
    narratives = _load_narratives() or None
    memo_facts = (
        dict(PROJECT_9199_FACTS) if project_id == DEFAULT_PROJECT_ID else {"project_id": project_id}
    )
    memo = build_memo(
        memo_facts.get("project_id", project_id),
        memo_facts,
        evidence_cards,
        findings,
        AuditLog(str(paths.audit_log)),
        narratives,
        reviewer_questions=_reviewer_questions_for_project(project_id, findings),
    )
    paths.memo.parent.mkdir(parents=True, exist_ok=True)
    paths.memo.write_text(memo_to_markdown(memo), encoding="utf-8")
    _run_script("scripts/build_review_pack.py", project_id)


def _regenerate_all_narratives(project_id: str, paths: ProjectPaths, evidence_cards, findings) -> None:
    from core.extractor import generate_all_narratives

    fact_topics: dict[str, str] = {}
    for card in evidence_cards:
        for fact_id in card.fact_ids:
            fact_topics.setdefault(fact_id, card.claim_topic)
    facts_records = (
        json.loads(paths.facts_file.read_text(encoding="utf-8"))
        if paths.facts_file.exists()
        else []
    )
    enriched_facts: list[dict] = []
    for fact in facts_records:
        record = dict(fact)
        topic = fact_topics.get(record.get("fact_id"))
        if topic:
            record["claim_topic"] = topic
        enriched_facts.append(record)
    card_dicts = [card.to_dict() for card in evidence_cards]
    _, chunks, _ = _load_processed_documents_cached(project_id)
    chunks_by_document: dict[str, list[dict]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(
            {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "document_id": chunk.document_id,
            }
        )
    narratives = generate_all_narratives(
        findings=findings,
        facts=enriched_facts,
        evidence_cards=card_dicts,
        chunks_by_document=chunks_by_document,
        project_context=_project_context_dict(project_id),
    )
    payload = {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": EXTRACTOR_MODEL,
        "narratives": narratives,
    }
    paths.narratives.parent.mkdir(parents=True, exist_ok=True)
    paths.narratives.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _regenerate_memo_with_narratives(project_id, evidence_cards, findings) -> None:
    paths = ProjectPaths(project_id, base_dir=ROOT)
    narratives_payload = (
        json.loads(paths.narratives.read_text(encoding="utf-8"))
        if paths.narratives.exists()
        else {}
    )
    narratives = narratives_payload.get("narratives") or None
    memo_facts = dict(PROJECT_9199_FACTS) if project_id == DEFAULT_PROJECT_ID else {"project_id": project_id}
    memo = build_memo(
        memo_facts.get("project_id", project_id),
        memo_facts,
        evidence_cards,
        findings,
        AuditLog(str(paths.audit_log)),
        narratives,
        reviewer_questions=_reviewer_questions_for_project(project_id, findings),
    )
    paths.memo.parent.mkdir(parents=True, exist_ok=True)
    paths.memo.write_text(memo_to_markdown(memo), encoding="utf-8")


def _regenerate_narrative_for_finding(finding, evidence_cards) -> None:
    paths = _current_paths()
    project_id = paths.project_id
    facts_records = json.loads(paths.facts_file.read_text(encoding="utf-8")) if paths.facts_file.exists() else []
    fact_topics: dict[str, str] = {}
    for card in evidence_cards:
        for fact_id in card.fact_ids:
            fact_topics.setdefault(fact_id, card.claim_topic)
    relevant_facts: list[dict] = []
    for fact in facts_records:
        record = dict(fact)
        topic = fact_topics.get(record.get("fact_id"))
        if topic:
            record["claim_topic"] = topic
        relevant_facts.append(record)

    from core.extractor import NARRATIVE_TOPIC_MAP

    topics = NARRATIVE_TOPIC_MAP.get(finding.flag_code)
    if topics is not None:
        filtered_facts = [f for f in relevant_facts if f.get("claim_topic") in topics]
        filtered_cards = [
            card.to_dict() for card in evidence_cards if card.claim_topic in topics
        ]
    else:
        filtered_facts = relevant_facts
        filtered_cards = [card.to_dict() for card in evidence_cards]

    _, chunks, _ = _load_processed_documents_cached(project_id)
    chunk_index: dict[str, dict] = {}
    for chunk in chunks:
        chunk_index[chunk.chunk_id] = {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "page_number": chunk.page_number,
        }
    relevant_chunks: list[dict] = []
    seen: set[str] = set()
    for fact in filtered_facts:
        for citation_id in fact.get("citation_ids", []) or []:
            chunk = chunk_index.get(citation_id)
            if chunk and chunk["chunk_id"] not in seen:
                seen.add(chunk["chunk_id"])
                relevant_chunks.append(chunk)
        if len(relevant_chunks) >= 3:
            break

    text = generate_finding_narrative(
        finding,
        filtered_facts,
        filtered_cards,
        relevant_chunks[:3],
        _project_context_dict(project_id),
    )

    payload = {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": EXTRACTOR_MODEL,
        "narratives": {},
    }
    if paths.narratives.exists():
        payload = json.loads(paths.narratives.read_text(encoding="utf-8"))
    payload.setdefault("narratives", {})[finding.flag_code] = text
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["model"] = EXTRACTOR_MODEL
    payload["project_id"] = project_id
    paths.narratives.parent.mkdir(parents=True, exist_ok=True)
    paths.narratives.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _append_disposition(finding_id: str, disposition: str, note: str, project_id: str) -> None:
    paths = ProjectPaths(project_id, base_dir=ROOT)
    paths.dispositions.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if paths.dispositions.exists():
        records = json.loads(paths.dispositions.read_text(encoding="utf-8"))
    records.append(
        {
            "finding_id": finding_id,
            "disposition": disposition,
            "note": note,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "actor": "human",
        }
    )
    paths.dispositions.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    _clear_data_caches()


def _run_script(script: str, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, script, *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout or ""


def _clear_data_caches() -> None:
    st.cache_data.clear()


def _badge(text: str, color: str) -> str:
    return f"<span class='badge' style='background:{color}'>{html.escape(text)}</span>"


def _pill(text: str, kind: str) -> str:
    """A soft, bordered status pill. kind in {ok, bad, warn, muted}."""
    return f"<span class='pill pill-{kind}'>{html.escape(text)}</span>"


def _severity_badge(severity: str) -> str:
    return _badge(severity, BADGE_COLORS.get(severity, "#475569"))


def _queue_flash(kind: str, message: str) -> None:
    """Queue a message to show at the top of the page after a rerun.

    Streamlit resets the active tab on rerun, so post-action messages are
    surfaced above the tabs where they remain visible regardless of tab.
    """
    st.session_state.setdefault("_flash", []).append((kind, message))


def _render_flashes() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        renderer = {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}
        renderer.get(kind, st.info)(message)


def _finding_plain_title(finding) -> str:
    from domain.risk_flags import RISK_FLAGS

    meta = RISK_FLAGS.get(finding.flag_code) or {}
    title = meta.get("title")
    if title:
        return str(title)
    description = (finding.description or "").strip()
    if description:
        first_sentence = description.split(".")[0].strip()
        return first_sentence or description
    return finding.flag_code


def _topic_color(topic: str) -> str:
    colors = {
        "baseline_methodology": "#2563eb",
        "additionality": "#7e22ce",
        "issuance": "#b42318",
        "deregistration": "#b42318",
        "monitoring": "#0f766e",
        "permanence": "#a15c00",
        "host_party_approval": "#16803c",
        "cancellations": "#c2410c",
    }
    return colors.get(topic, "#475569")


def _status_color(status: str) -> str:
    return {
        "pending": "#475569",
        "confirm": "#16803c",
        "edit": "#2563eb",
        "reject": "#b42318",
    }.get(status, "#475569")


def _source_method_badge(extraction_method: str) -> str:
    labels = {
        "manual_curation": ("[MANUALLY CURATED]", "#475569"),
        "ai_extracted_confirmed": ("[AI EXTRACTED — human confirmed]", "#16803c"),
        "ai_extracted_edited": ("[AI EXTRACTED — human edited]", "#2563eb"),
    }
    label, color = labels.get(extraction_method, (f"[{extraction_method or 'UNKNOWN SOURCE'}]", "#475569"))
    return _badge(label, color)


def _source_label(text: str) -> str:
    return f"<span class='source-label'>{html.escape(text)}</span>"


def _title_key(value: str) -> str:
    return value.replace("_", " ").title()


def _display_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


def _trim(text: str, length: int) -> str:
    compact = " ".join(text.split())
    return compact[:length] + ("..." if len(compact) > length else "")


def _file_size(path: str) -> str:
    source = Path(path)
    if not source.exists():
        return "not held"
    size = source.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def _highlight_terms(text: str, terms: list[str]) -> str:
    escaped = html.escape(text)
    for term in sorted({term for term in terms if term}, key=len, reverse=True):
        escaped = escaped.replace(html.escape(term), f"<mark>{html.escape(term)}</mark>")
        escaped = escaped.replace(html.escape(term.title()), f"<mark>{html.escape(term.title())}</mark>")
        escaped = escaped.replace(html.escape(term.upper()), f"<mark>{html.escape(term.upper())}</mark>")
    return f"<pre style='white-space:pre-wrap'>{escaped}</pre>"


def _memo_metadata(text: str, audit_events: list[dict[str, Any]]) -> dict[str, str]:
    metadata = {"memo_id": "memo-project-9199", "generated_at": "not generated", "content_hash": ""}
    for line in text.splitlines():
        if line.startswith("Memo ID:"):
            metadata["memo_id"] = line.split(":", 1)[1].strip()
        if line.startswith("Generated at:"):
            metadata["generated_at"] = line.split(":", 1)[1].strip()
        if line.startswith("Content hash:"):
            metadata["content_hash"] = line.split(":", 1)[1].strip()
    if not metadata["generated_at"] and audit_events:
        metadata["generated_at"] = audit_events[-1].get("timestamp", "")
    return metadata


def _parse_memo_sections(text: str) -> list[tuple[str, str]]:
    sections = []
    current_title = None
    current_lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:]
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def _split_source_line(body: str) -> tuple[str, str]:
    lines = body.splitlines()
    if lines and lines[0].startswith("["):
        return lines[0], "\n".join(lines[1:]).strip()
    return "", body


def _citation_ids_from_text(text: str) -> list[str]:
    ids = []
    for token in text.replace("[", " [").replace("]", "] ").split():
        if token.startswith("[cit-") and token.endswith("]"):
            ids.append(token.strip("[]"))
    return ids


def _html_table(rows: list[dict[str, str]]) -> str:
    headers = rows[0].keys()
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{row[header]}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


if __name__ == "__main__":
    main()
