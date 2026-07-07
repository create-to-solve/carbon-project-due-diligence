from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.models import Citation, DocumentChunk, ParsedDocument

PARSER_VERSION = "1.0"
LEGACY_PROJECT_ID = "project_9199"
LEGACY_FALLBACK_FACT_PROJECT_ID = "9199"
MAX_DOCUMENT_ID_LENGTH = 60


def read_registry(registry_path: str | Path, project_id: str | None = None) -> list[dict]:
    path = Path(registry_path)
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    if project_id is not None:
        return [record for record in records if record.get("project_id") == project_id]
    return records


def write_registry(records: list[dict | ParsedDocument], registry_path: str | Path) -> list[dict]:
    path = Path(registry_path)
    existing = read_registry(path)
    by_document_id = {record["document_id"]: record for record in existing}
    for record in records:
        normalized = _registry_record(record, path)
        by_document_id[normalized["document_id"]] = normalized
    updated = list(by_document_id.values())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, indent=2, sort_keys=True), encoding="utf-8")
    return updated


def _registry_record(record: dict | ParsedDocument, registry_path: Path) -> dict:
    if isinstance(record, dict):
        payload = dict(record)
    else:
        payload = record.to_dict()
    project_id = str(payload.get("project_id", ""))
    source_path = _registry_source_path(payload.get("source_path", ""), registry_path)
    return {
        "document_id": payload["document_id"],
        "project_id": project_id,
        "filename": Path(str(payload.get("source_path", ""))).name,
        "document_type": payload.get("document_type", "unknown"),
        "title": payload.get("title", ""),
        "source_path": source_path,
        "ingested_at": payload.get("ingested_at") or payload.get("parsed_at", ""),
        "page_count": payload.get("page_count", 0),
        "chunk_count": payload.get("chunk_count", 0),
        "parse_status": payload.get("parse_status", ""),
        "parse_warnings": payload.get("parse_warnings", []),
    }


def _registry_source_path(source_path: str, registry_path: Path) -> str:
    path = Path(source_path)
    if not path.is_absolute():
        return path.as_posix()
    project_root = registry_path.resolve().parents[2]
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def parse(
    file_path: str, project_id: str = LEGACY_PROJECT_ID
) -> tuple[ParsedDocument, list[DocumentChunk]]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path, project_id)
    if suffix in {".txt", ".md"}:
        return _parse_text(path, project_id)
    raise ValueError(f"Unsupported document type: {suffix}")


def detect_document_type(filename: str) -> str:
    name = Path(filename).name.lower()
    if "validation" in name:
        return "validation_report"
    if "monitoring" in name:
        return "monitoring_report"
    if "pdd" in name:
        return "pdd"
    return "unknown"


def citations_from_chunks(chunks: list[DocumentChunk], document: ParsedDocument) -> list[Citation]:
    citations = []
    for index, chunk in enumerate(chunks, start=1):
        citations.append(
            Citation(
                citation_id=f"cit-{document.document_id}-{index:03d}",
                document_id=document.document_id,
                chunk_id=chunk.chunk_id,
                section_heading=chunk.heading,
                page_number=chunk.page_number,
                paragraph_number=chunk.paragraph_number,
                source_path=chunk.source_path,
                excerpt=_excerpt(chunk.text),
            )
        )
    return citations


def _parse_pdf(
    path: Path, project_id: str = LEGACY_PROJECT_ID
) -> tuple[ParsedDocument, list[DocumentChunk]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "PDF parsing requires pdfplumber. Install with: pip install pdfplumber"
        ) from exc

    document_id = _document_id(path, project_id)
    warnings: list[str] = []
    page_records: list[tuple[int, str, str | None]] = []
    page_count = 0
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover - parser-specific edge
                text = ""
                warnings.append(f"page {page_num}: {exc}")
            if not text.strip():
                warnings.append(f"page {page_num}: no extractable text")
                continue
            stripped = text.strip()
            page_records.append((page_num, stripped, _heading_from_page_text(stripped)))
    empty_pages = page_count - len(page_records)
    chunk_status = "partial" if page_count and empty_pages / page_count > 0.2 else "success"
    chunks = [
        DocumentChunk(
            chunk_id=f"{document_id}-page-{page_num:03d}",
            document_id=document_id,
            heading=heading,
            text=text,
            page_number=page_num,
            line_start=None,
            line_end=None,
            paragraph_number=page_num,
            source_path=str(path),
            parser_name="pdfplumber",
            parse_status=chunk_status,
        )
        for page_num, text, heading in page_records
    ]
    parse_status = "success" if chunks else "failed"
    if not chunks and page_count:
        warnings.append("failed: no extractable text found in PDF")
    return _document(
        path,
        document_id,
        "pdf",
        "pdfplumber",
        parse_status,
        warnings,
        page_count,
        project_id,
    ), chunks


def _heading_from_page_text(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if len(candidate) < 60 or candidate.isupper():
            return candidate
        return None
    return None


def _parse_text(
    path: Path, project_id: str = LEGACY_PROJECT_ID
) -> tuple[ParsedDocument, list[DocumentChunk]]:
    text = path.read_text(encoding="utf-8")
    document_id = _document_id(path, project_id)
    chunks: list[DocumentChunk] = []
    heading = "Document"
    paragraph_lines: list[tuple[int, str]] = []
    paragraph_number = 0

    def flush() -> None:
        nonlocal paragraph_number
        if not paragraph_lines:
            return
        paragraph_number += 1
        line_start = paragraph_lines[0][0]
        line_end = paragraph_lines[-1][0]
        body = "\n".join(line for _, line in paragraph_lines).strip()
        if body:
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}-chunk-{len(chunks) + 1:03d}",
                    document_id=document_id,
                    heading=heading,
                    text=body,
                    page_number=None,
                    line_start=line_start,
                    line_end=line_end,
                    paragraph_number=paragraph_number,
                    source_path=str(path),
                    parser_name="text_heuristic",
                    parse_status="success",
                )
            )
        paragraph_lines.clear()

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if re.match(r"^#{2,3}\s+", line):
            flush()
            heading = re.sub(r"^#{2,3}\s+", "", line).strip()
            continue
        if not line.strip():
            flush()
            continue
        paragraph_lines.append((line_number, line))
    flush()

    parse_status = "success" if chunks else "failed"
    warnings = [] if chunks else ["no chunks created"]
    return _document(
        path,
        document_id,
        suffix_label(path),
        "text_heuristic",
        parse_status,
        warnings,
        0,
        project_id,
    ), chunks


def _document(
    path: Path,
    document_id: str,
    file_type: str,
    parser_name: str,
    parse_status: str,
    parse_warnings: list[str],
    page_count: int,
    project_id: str = LEGACY_PROJECT_ID,
) -> ParsedDocument:
    fact_project_id = (
        LEGACY_FALLBACK_FACT_PROJECT_ID if project_id == LEGACY_PROJECT_ID else project_id
    )
    return ParsedDocument(
        document_id=document_id,
        title=_title(path, project_id, document_id),
        source_url=_source_url(document_id),
        source_path=str(path),
        file_type=file_type,
        project_id=fact_project_id,
        document_type=detect_document_type(path.name),
        parser_name=parser_name,
        parser_version=PARSER_VERSION,
        parse_status=parse_status,
        parse_warnings=parse_warnings,
        page_count=page_count,
        parsed_at=datetime.now(timezone.utc).isoformat(),
    )


def _document_id(path: Path, project_id: str = LEGACY_PROJECT_ID) -> str:
    if project_id == LEGACY_PROJECT_ID:
        legacy_id = _legacy_document_id(path)
        if legacy_id is not None:
            return legacy_id
    slug = project_id.replace("_", "-")[:20].strip("-") or "project"
    file_hash = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:8]
    return f"doc-{slug}-{file_hash}"[:MAX_DOCUMENT_ID_LENGTH]


def _legacy_document_id(path: Path) -> str | None:
    name = path.name.lower()
    stem = path.stem.lower()
    if name == "validation_report_9199.pdf":
        return "doc-9199-val"
    if name == "monitoring_report_9199_2016_2020.pdf":
        return "doc-9199-mon2"
    if "validation" in stem:
        return "doc-9199-val"
    if "monitoring" in stem or "mon2" in stem:
        return "doc-9199-mon2"
    return None


def _title(path: Path, project_id: str = LEGACY_PROJECT_ID, document_id: str = "") -> str:
    if project_id == LEGACY_PROJECT_ID:
        if document_id == "doc-9199-val":
            return "Validation Report for CDM Project 9199"
        if document_id == "doc-9199-mon2":
            return "Monitoring Report 2016-2020 for CDM Project 9199"
    return path.stem.replace("_", " ").replace("-", " ").title()


def _source_url(document_id: str) -> str:
    if document_id == "doc-9199-val":
        return "https://cdm.unfccc.int/UserManagement/FileStorage/9JUF31R8YCAHX7DIEWNZ6SPL2KMQ5G"
    if document_id == "doc-9199-mon2":
        return "https://cdm.unfccc.int/UserManagement/FileStorage/5CTB6JZHI42A3SXNKO97LR0GQ8WDFV"
    return ""


def suffix_label(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _excerpt(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:200]
