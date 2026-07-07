from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParsedDocument:
    document_id: str
    title: str
    source_url: str
    source_path: str
    file_type: str
    project_id: str
    document_type: str
    parser_name: str
    parser_version: str
    parse_status: str
    parse_warnings: list[str]
    page_count: int
    parsed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    heading: str
    text: str
    page_number: int | None
    line_start: int | None
    line_end: int | None
    paragraph_number: int | None
    source_path: str
    parser_name: str
    parse_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Citation:
    citation_id: str
    document_id: str
    chunk_id: str
    section_heading: str
    page_number: int | None
    paragraph_number: int | None
    source_path: str
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedFact:
    fact_id: str
    label: str
    value: Any
    unit: str | None
    source_document_id: str
    citation_ids: list[str]
    extraction_method: str
    confidence: float
    notes: str
    extracted_at: str
    search_terms: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCard:
    card_id: str
    claim: str
    claim_topic: str
    fact_ids: list[str]
    citation_ids: list[str]
    evidence_role: str
    review_status: str
    reviewer_note: str
    conflicts_with: list[str]
    subject_id: str
    subject_type: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    finding_id: str
    flag_code: str
    severity: str
    description: str
    evidence_gap: str
    required_documents: list[str]
    evidence_card_ids: list[str]
    review_status: str
    reviewer_disposition: str
    reviewer_note: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    subject_id: str
    subject_type: str
    timestamp: str
    actor: str
    lab_origin: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewerMemo:
    memo_id: str
    project_id: str
    document_ids: list[str]
    generated_at: str
    sections: dict[str, str]
    open_findings: list[str]
    evidence_gaps: list[str]
    reviewer_questions: list[str]
    audit_event_ids: list[str]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseMemory:
    case_id: str
    project_id: str
    subject_id: str
    snapshot_timestamp: str
    event_count: int
    content_hash: str
    timeline: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
