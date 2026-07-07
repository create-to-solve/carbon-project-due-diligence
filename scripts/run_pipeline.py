from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.audit import (  # noqa: E402
    AuditLog,
    emit_case_snapshot_taken,
    emit_chunks_created,
    emit_citations_created,
    emit_conflict_detected,
    emit_document_ingested,
    emit_evidence_card_created,
    emit_facts_curated,
    emit_finding_flagged,
    emit_memo_generated,
    emit_narratives_generated,
)
from core.case_memory import build_case_snapshot  # noqa: E402
from core.evidence import detect_conflicts, load_evidence_cards, load_facts  # noqa: E402
from core.extractor import MODEL as EXTRACTOR_MODEL, generate_all_narratives  # noqa: E402
from core.memo import build_memo, memo_to_markdown, reviewer_questions_for  # noqa: E402
from core.models import Citation, DocumentChunk, ParsedDocument  # noqa: E402
from core.paths import ProjectPaths  # noqa: E402
from core.project_manager import (  # noqa: E402
    get_project,
    load_project_registry,
    update_project_counts,
)
from domain.project_9199 import PROJECT_9199_FACTS  # noqa: E402
from domain.rule_router import run_checks_for_project  # noqa: E402
from scripts.run_ingestion import ingest_paths, select_source_paths  # noqa: E402

DEFAULT_PROJECT_ID = "project_9199"
PROJECT_ID = DEFAULT_PROJECT_ID
_DEFAULT_PATHS = ProjectPaths(DEFAULT_PROJECT_ID, base_dir=ROOT)
DATA_DIR = _DEFAULT_PATHS.data
RAW_DIR = _DEFAULT_PATHS.raw_documents
PROCESSED_DIR = _DEFAULT_PATHS.processed_documents
FACTS_PATH = _DEFAULT_PATHS.facts_file
CARDS_PATH = _DEFAULT_PATHS.evidence_cards_file
AUDIT_PATH = _DEFAULT_PATHS.audit_log
MEMO_PATH = _DEFAULT_PATHS.memo
SNAPSHOT_PATH = _DEFAULT_PATHS.case_memory
NARRATIVES_PATH = _DEFAULT_PATHS.narratives


def main(project_id: str = DEFAULT_PROJECT_ID) -> None:
    paths = ProjectPaths(project_id, base_dir=ROOT)
    registry_path = paths.project_registry
    project_record = get_project(project_id, str(registry_path))
    methodology_type = (project_record or {}).get("methodology_type", "cdm_ar")

    facts = _initial_facts(project_id, project_record)
    _ensure_placeholder_documents(paths)
    audit_log = AuditLog(str(paths.audit_log))

    source_paths, using_real_pdfs = select_source_paths(paths.raw_documents)
    parsed_documents, all_chunks, all_citations = _load_or_ingest_documents(
        paths, source_paths, using_real_pdfs
    )
    if parsed_documents:
        if using_real_pdfs:
            print(f"[DOCUMENTS] Using real PDFs: {len(source_paths)}")
        else:
            print(f"[DOCUMENTS] Using placeholders: {len(source_paths)}")
    else:
        print("[DOCUMENTS] No documents found for project — running with empty corpus.")

    for document in parsed_documents:
        chunks = [chunk for chunk in all_chunks if chunk.document_id == document.document_id]
        citations = [
            citation for citation in all_citations if citation.document_id == document.document_id
        ]
        emit_document_ingested(audit_log, document.document_id, document.title, len(chunks), document.parse_status)
        emit_chunks_created(audit_log, document.document_id, [chunk.chunk_id for chunk in chunks])
        emit_citations_created(audit_log, document.document_id, [citation.citation_id for citation in citations])

    curated_facts = _load_facts_safely(paths.facts_file)
    _merge_curated_facts_into_facts(facts, curated_facts)

    evidence_cards = _load_cards_safely(paths.evidence_cards_file)
    for document_id in sorted({fact.source_document_id for fact in curated_facts}):
        fact_ids = [fact.fact_id for fact in curated_facts if fact.source_document_id == document_id]
        emit_facts_curated(audit_log, document_id, fact_ids)
    for card in evidence_cards:
        emit_evidence_card_created(audit_log, card.card_id, card.claim_topic, card.evidence_role)
    for card_a_id, card_b_id, claim_topic in detect_conflicts(evidence_cards):
        emit_conflict_detected(audit_log, card_a_id, card_b_id, claim_topic)

    findings = run_checks_for_project(facts, methodology_type)
    for finding in findings:
        emit_finding_flagged(audit_log, facts.get("project_id", project_id), finding.finding_id, finding.flag_code, finding.severity)

    reviewer_questions = reviewer_questions_for(project_record, findings)
    memo = build_memo(
        facts.get("project_id", project_id),
        facts,
        evidence_cards,
        findings,
        audit_log,
        reviewer_questions=reviewer_questions,
    )
    emit_memo_generated(audit_log, facts.get("project_id", project_id), memo.memo_id, len(findings), len(memo.evidence_gaps))

    narratives = _generate_and_save_narratives(
        findings=findings,
        curated_facts=curated_facts,
        evidence_cards=evidence_cards,
        chunks=all_chunks,
        project_context=facts,
        audit_log=audit_log,
        project_id=facts.get("project_id", project_id),
        narratives_path=paths.narratives,
    )

    memo = build_memo(
        facts.get("project_id", project_id),
        facts,
        evidence_cards,
        findings,
        audit_log,
        narratives,
        reviewer_questions=reviewer_questions,
    )
    paths.memo.parent.mkdir(parents=True, exist_ok=True)
    paths.memo.write_text(memo_to_markdown(memo), encoding="utf-8")

    snapshot_subject = f"project-{facts.get('project_id', project_id)}"
    snapshot = build_case_snapshot(
        audit_log,
        project_id=facts.get("project_id", project_id),
        subject_id=snapshot_subject,
        case_id=f"case-{snapshot_subject}",
        output_path=str(paths.case_memory),
    )
    emit_case_snapshot_taken(
        audit_log,
        facts.get("project_id", project_id),
        snapshot.case_id,
        snapshot.content_hash,
        snapshot.event_count,
    )

    if project_record is not None:
        update_project_counts(
            project_id,
            str(registry_path),
            document_count=len(parsed_documents),
            facts_count=len(curated_facts),
            findings_count=len(findings),
        )

    _write_pipeline_state(
        paths=paths,
        project_id=project_id,
        document_count=len(parsed_documents),
        facts_count=len(curated_facts),
        findings=findings,
        memo_path=paths.memo,
        case_hash=snapshot.content_hash,
    )

    _print_summary(
        project_id=project_id,
        memo_path=paths.memo,
        documents=len(parsed_documents),
        chunks=len(all_chunks),
        facts=len(curated_facts),
        cards=len(evidence_cards),
        findings=findings,
        audit_events=len(audit_log.read()),
        case_hash=snapshot.content_hash,
    )


def _write_pipeline_state(
    paths: ProjectPaths,
    project_id: str,
    document_count: int,
    facts_count: int,
    findings,
    memo_path: Path,
    case_hash: str,
) -> Path:
    critical_count = sum(1 for finding in findings if finding.severity == "Critical")
    state_path = paths.pipeline_state
    state = {
        "project_id": project_id,
        "document_count": document_count,
        "facts_count": facts_count,
        "findings_count": len(findings),
        "critical_count": critical_count,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "memo_path": str(memo_path.relative_to(paths.base)) if memo_path.exists() else None,
        "case_hash": case_hash,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state_path


def _initial_facts(project_id: str, project_record: dict | None) -> dict:
    if project_id == DEFAULT_PROJECT_ID:
        return dict(PROJECT_9199_FACTS)
    if project_record is None:
        return {"project_id": project_id}
    return {
        "project_id": project_id,
        "title": project_record.get("display_name", project_id),
        "host_country": project_record.get("host_country"),
        "methodology": project_record.get("methodology"),
    }


def _merge_curated_facts_into_facts(facts: dict, curated_facts) -> None:
    for fact in curated_facts:
        key = (fact.label or "").strip().lower().replace(" ", "_")
        if key and key not in facts:
            facts[key] = fact.value


def _load_facts_safely(path: Path):
    if not path.exists():
        return []
    return load_facts(str(path))


def _load_cards_safely(path: Path):
    if not path.exists():
        return []
    return load_evidence_cards(str(path))


def _generate_and_save_narratives(
    findings,
    curated_facts,
    evidence_cards,
    chunks,
    project_context,
    audit_log: AuditLog,
    project_id: str,
    narratives_path: Path,
):
    if not findings:
        return None
    if not os.environ.get("OPENAI_API_KEY"):
        print("Narratives: skipped — OPENAI_API_KEY not set")
        return None

    fact_topics: dict[str, str] = {}
    for card in evidence_cards:
        for fact_id in card.fact_ids:
            fact_topics.setdefault(fact_id, card.claim_topic)

    fact_dicts: list[dict] = []
    for fact in curated_facts:
        record = fact.to_dict()
        topic = fact_topics.get(fact.fact_id)
        if topic:
            record["claim_topic"] = topic
        fact_dicts.append(record)

    card_dicts = [card.to_dict() for card in evidence_cards]

    chunks_by_document: dict[str, list] = {}
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
        facts=fact_dicts,
        evidence_cards=card_dicts,
        chunks_by_document=chunks_by_document,
        project_context=project_context,
    )

    narratives_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": EXTRACTOR_MODEL,
        "narratives": narratives,
    }
    narratives_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    emit_narratives_generated(
        audit_log,
        project_id,
        len(narratives),
        EXTRACTOR_MODEL,
        str(narratives_path),
    )
    print(f"Narratives: {len(narratives)} finding narratives generated")
    return narratives


def _load_or_ingest_documents(
    paths: ProjectPaths, source_paths: list[Path], using_real_pdfs: bool
) -> tuple[list[ParsedDocument], list[DocumentChunk], list[Citation]]:
    if not source_paths:
        return _load_processed_documents(paths.processed_documents)
    if not _processed_outputs_ready(paths.processed_documents, source_paths, using_real_pdfs, paths.project_id):
        ingest_paths(
            source_paths,
            paths.processed_documents,
            paths.project_id,
            paths.document_registry,
        )
    return _load_processed_documents(paths.processed_documents)


def _processed_outputs_ready(
    processed_dir: Path,
    source_paths: list[Path],
    using_real_pdfs: bool,
    project_id: str = "project_9199",
) -> bool:
    expected_ids = {_expected_document_id(path, project_id) for path in source_paths}
    parsed_paths = [processed_dir / f"{document_id}_parsed_document.json" for document_id in expected_ids]
    chunk_paths = [processed_dir / f"{document_id}_chunks.json" for document_id in expected_ids]
    citation_paths = [processed_dir / f"{document_id}_citations.json" for document_id in expected_ids]
    if not all(path.exists() for path in [*parsed_paths, *chunk_paths, *citation_paths]):
        return False
    if using_real_pdfs:
        for path in parsed_paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("file_type") != "pdf":
                return False
    return True


def _load_processed_documents(processed_dir: Path) -> tuple[list[ParsedDocument], list[DocumentChunk], list[Citation]]:
    documents: list[ParsedDocument] = []
    chunks: list[DocumentChunk] = []
    citations: list[Citation] = []
    if not processed_dir.exists():
        return documents, chunks, citations
    for document_path in sorted(processed_dir.glob("*_parsed_document.json")):
        document = ParsedDocument(**json.loads(document_path.read_text(encoding="utf-8")))
        documents.append(document)
        chunks_path = processed_dir / f"{document.document_id}_chunks.json"
        citations_path = processed_dir / f"{document.document_id}_citations.json"
        if chunks_path.exists():
            chunks.extend(
                DocumentChunk(**item)
                for item in json.loads(chunks_path.read_text(encoding="utf-8"))
            )
        if citations_path.exists():
            citations.extend(
                Citation(**item)
                for item in json.loads(citations_path.read_text(encoding="utf-8"))
            )
    return documents, chunks, citations


def _expected_document_id(path: Path, project_id: str = "project_9199") -> str:
    from core.ingestion import _document_id

    return _document_id(path, project_id)


def _ensure_placeholder_documents(paths: ProjectPaths) -> None:
    if paths.project_id != DEFAULT_PROJECT_ID:
        return
    raw_dir = paths.raw_documents
    raw_dir.mkdir(parents=True, exist_ok=True)
    if list(raw_dir.glob("*.pdf")) or list(raw_dir.glob("*.txt")) or list(raw_dir.glob("*.md")):
        return
    placeholders = {
        "validation_report_project_9199_placeholder.txt": (
            "## Validation Report for CDM Project 9199\n\n"
            "Document title: Validation Report\n"
            "Source URL: https://cdm.unfccc.int/UserManagement/FileStorage/9JUF31R8YCAHX7DIEWNZ6SPL2KMQ5G\n"
            "Project ID: 9199\n"
            "Date: 2026-06-28\n"
            "Note: Placeholder pending manual download.\n"
        ),
        "monitoring_report_2016_2020_project_9199_placeholder.txt": (
            "## Monitoring Report 2016-2020 for CDM Project 9199\n\n"
            "Document title: Monitoring Report 2016-2020\n"
            "Source URL: https://cdm.unfccc.int/UserManagement/FileStorage/5CTB6JZHI42A3SXNKO97LR0GQ8WDFV\n"
            "Project ID: 9199\n"
            "Date: 2026-06-28\n"
            "Note: Placeholder pending manual download.\n"
        ),
    }
    for filename, text in placeholders.items():
        (raw_dir / filename).write_text(text, encoding="utf-8")


def _print_summary(
    project_id, memo_path, documents, chunks, facts, cards, findings, audit_events, case_hash
) -> None:
    buckets = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for finding in findings:
        if finding.severity in buckets:
            buckets[finding.severity].append(finding.flag_code)
    print(f"=== Carbon DD v1 — {project_id} Pipeline ===")
    print(f"Documents ingested: {documents}")
    print(f"Chunks created: {chunks}")
    print(f"Facts loaded: {facts}")
    print(f"Evidence cards: {cards}")
    print(f"Findings: {len(findings)}")
    for severity in ["Critical", "High", "Medium", "Low"]:
        flags = ", ".join(buckets[severity])
        print(f"  {severity}: {len(buckets[severity])} ({flags})")
    print(f"Memo: {memo_path.relative_to(ROOT)}")
    print(f"Audit events: {audit_events}")
    print(f"Case memory hash: {case_hash[:16]}...")
    print("============================================")


def _list_projects() -> None:
    registry = load_project_registry(str(_DEFAULT_PATHS.project_registry))
    if not registry:
        print("No projects in registry.")
        return
    print(f"{'PROJECT_ID':<32} {'STATUS':<14} {'METHOD':<10} DISPLAY NAME")
    for project in registry:
        print(
            f"{project.get('project_id', ''):<32} "
            f"{project.get('status', ''):<14} "
            f"{project.get('methodology_type', ''):<10} "
            f"{project.get('display_name', '')}"
        )


def _parse_args(argv: list[str]) -> tuple[str, bool]:
    parser = argparse.ArgumentParser(description="Run the Carbon DD v1 pipeline.")
    parser.add_argument(
        "project_id",
        nargs="?",
        default=DEFAULT_PROJECT_ID,
        help="Project ID to run the pipeline for (default: project_9199)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all projects in the registry and exit.",
    )
    args = parser.parse_args(argv)
    return args.project_id, args.list


if __name__ == "__main__":
    project_id, list_only = _parse_args(sys.argv[1:])
    if list_only:
        _list_projects()
    else:
        main(project_id)
