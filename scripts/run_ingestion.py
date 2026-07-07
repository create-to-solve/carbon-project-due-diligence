from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.audit import AuditLog, emit_ai_extraction_completed, generate_event_id, now_utc_iso  # noqa: E402
from core.evidence import load_proposals, save_proposals  # noqa: E402
from core.extractor import MODEL, build_proposals, extract_facts_from_document  # noqa: E402
from core.ingestion import citations_from_chunks, parse, write_registry  # noqa: E402
from core.models import AuditEvent  # noqa: E402
from core.paths import ProjectPaths  # noqa: E402
from core.project_manager import get_project, load_project_registry  # noqa: E402
from domain.project_9199 import PROJECT_9199_FACTS  # noqa: E402

DEFAULT_PROJECT_ID = "project_9199"
PROJECT_ID = DEFAULT_PROJECT_ID
_DEFAULT_PATHS = ProjectPaths(DEFAULT_PROJECT_ID, base_dir=ROOT)
DATA_DIR = _DEFAULT_PATHS.data
RAW_DIR = _DEFAULT_PATHS.raw_documents
PROCESSED_DIR = _DEFAULT_PATHS.processed_documents
REGISTRY_PATH = _DEFAULT_PATHS.document_registry
AUDIT_PATH = _DEFAULT_PATHS.audit_log
PROPOSALS_PATH = _DEFAULT_PATHS.proposals_file


def main(project_id: str = DEFAULT_PROJECT_ID) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = ProjectPaths(project_id, base_dir=ROOT)
    source_paths, using_real_pdfs = select_source_paths(paths.raw_documents)
    if not source_paths:
        raise SystemExit(
            f"No source documents found in {paths.raw_documents.relative_to(ROOT)}"
        )
    if using_real_pdfs:
        print("Real PDFs found — using actual documents")
    else:
        print("No PDFs found — using placeholders")
    ingest_paths(
        source_paths,
        paths.processed_documents,
        project_id,
        paths.document_registry,
    )


def select_source_paths(raw_dir: Path) -> tuple[list[Path], bool]:
    files = [path for path in raw_dir.iterdir() if path.is_file()] if raw_dir.exists() else []
    real_pdfs = sorted(path for path in files if path.suffix.lower() == ".pdf")
    placeholders = sorted(
        path for path in files if path.name.lower().endswith("_placeholder.txt")
    )
    if real_pdfs:
        return real_pdfs, True
    return placeholders, False


def ingest_paths(
    paths: list[Path],
    processed_dir: Path = PROCESSED_DIR,
    project_id: str = PROJECT_ID,
    registry_path: Path | None = None,
) -> list[dict]:
    processed_dir.mkdir(parents=True, exist_ok=True)
    registry_records = []
    should_write_registry = registry_path is not None or processed_dir == PROCESSED_DIR
    registry_path = registry_path or REGISTRY_PATH
    project_paths = ProjectPaths(project_id, base_dir=ROOT)
    audit_log = AuditLog(str(project_paths.audit_log))
    for path in paths:
        _warn_if_project_mismatch(path, project_id, audit_log)
        document, chunks = parse(str(path), project_id)
        document.project_id = project_id
        citations = citations_from_chunks(chunks, document)
        write_processed_outputs(document, chunks, citations, processed_dir)
        registry_records.append(
            {
                **document.to_dict(),
                "project_id": project_id,
                "filename": path.name,
                "ingested_at": document.parsed_at,
                "chunk_count": len(chunks),
            }
        )
        empty_pages = max(document.page_count - len(chunks), 0) if document.file_type == "pdf" else 0
        print(f"Document: {document.title}")
        print(f"Type: {document.document_type}")
        print(f"Pages: {document.page_count}")
        print(f"Chunks: {len(chunks)} ({empty_pages} pages empty/skipped)")
        print(f"Citations: {len(citations)}")
        print(f"Parse status: {document.parse_status}")
        print(f"Warnings: {len(document.parse_warnings)}")
        _run_ai_extraction(document, chunks, project_id, audit_log, project_paths)
    if should_write_registry:
        write_registry(registry_records, registry_path)
    return registry_records


def write_processed_outputs(document, chunks, citations, processed_dir: Path) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    (processed_dir / f"{document.document_id}_parsed_document.json").write_text(
        json.dumps(document.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (processed_dir / f"{document.document_id}_chunks.json").write_text(
        json.dumps([chunk.to_dict() for chunk in chunks], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (processed_dir / f"{document.document_id}_citations.json").write_text(
        json.dumps([citation.to_dict() for citation in citations], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    combined_output = processed_dir / f"{document.document_id}_processed.json"
    combined_output.write_text(
        json.dumps(
            {
                "document": document.to_dict(),
                "chunks": [chunk.to_dict() for chunk in chunks],
                "citations": [citation.to_dict() for citation in citations],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _warn_if_project_mismatch(path: Path, project_id: str, audit_log: AuditLog) -> None:
    detected_id = next(
        (
            value
            for value in re.findall(r"\d{4,}", path.name)
            if value not in project_id and not _is_plausible_year(value)
        ),
        None,
    )
    if detected_id is None:
        return
    summary = (
        f"Warning: {path.name} may belong to a different project. "
        "Ingesting anyway — verify this is the correct document."
    )
    print(summary)
    audit_log.write(
        AuditEvent(
            event_id=generate_event_id(),
            event_type="ingestion_project_mismatch_warning",
            subject_id=path.name,
            subject_type="document",
            timestamp=now_utc_iso(),
            actor="system",
            lab_origin="carbon-dd-v1",
            summary=summary,
            details={
                "filename": path.name,
                "detected_id": detected_id,
                "current_project": project_id,
            },
        )
    )


def _is_plausible_year(value: str) -> bool:
    try:
        year = int(value)
    except ValueError:
        return False
    return 1990 <= year <= 2035


def _run_ai_extraction(
    document,
    chunks,
    project_id: str,
    audit_log: AuditLog,
    project_paths: ProjectPaths | None = None,
) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("AI extraction skipped — OPENAI_API_KEY not set")
        return
    project_paths = project_paths or ProjectPaths(project_id, base_dir=ROOT)
    project_context = _project_context_for(project_id)
    facts = extract_facts_from_document(
        document,
        chunks,
        project_context,
        max_chunks=30,
        min_confidence=0.7,
    )
    proposals = build_proposals(facts, project_id)
    existing = load_proposals(str(project_paths.proposals_file))
    save_proposals(existing + proposals, str(project_paths.proposals_file))
    chunks_sent = min(30, len(chunks))
    print(f"AI extraction: {len(proposals)} fact proposals generated for {document.document_id}")
    emit_ai_extraction_completed(
        audit_log,
        document.document_id,
        proposal_count=len(proposals),
        chunks_sent=chunks_sent,
        model=MODEL,
    )


def _project_context_for(project_id: str) -> dict:
    if project_id == DEFAULT_PROJECT_ID:
        return dict(PROJECT_9199_FACTS)
    registry_path = _DEFAULT_PATHS.project_registry
    record = get_project(project_id, str(registry_path)) or {}
    return {
        "project_id": project_id,
        "title": record.get("display_name", project_id),
        "host_country": record.get("host_country"),
        "methodology": record.get("methodology"),
    }


def _list_projects() -> None:
    registry = load_project_registry(str(_DEFAULT_PATHS.project_registry))
    if not registry:
        print("No projects in registry.")
        return
    for project in registry:
        print(
            f"{project.get('project_id', ''):<32} "
            f"{project.get('status', ''):<14} "
            f"{project.get('methodology_type', ''):<10} "
            f"{project.get('display_name', '')}"
        )


def _parse_args(argv: list[str]) -> tuple[str, bool]:
    parser = argparse.ArgumentParser(description="Run document ingestion.")
    parser.add_argument(
        "project_id",
        nargs="?",
        default=DEFAULT_PROJECT_ID,
        help="Project ID to ingest documents for (default: project_9199)",
    )
    parser.add_argument("--list", action="store_true", help="List projects and exit.")
    args = parser.parse_args(argv)
    return args.project_id, args.list


if __name__ == "__main__":
    project_id, list_only = _parse_args(sys.argv[1:])
    if list_only:
        _list_projects()
    else:
        main(project_id)
