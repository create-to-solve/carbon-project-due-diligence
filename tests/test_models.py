import json

from core.models import (
    AuditEvent,
    CaseMemory,
    Citation,
    DocumentChunk,
    EvidenceCard,
    ExtractedFact,
    Finding,
    ParsedDocument,
    ReviewerMemo,
)


def test_all_dataclasses_instantiate_with_required_fields():
    parsed = ParsedDocument(
        "doc-1",
        "Title",
        "https://example.test",
        "data/documents/raw/doc.txt",
        "txt",
        "9199",
        "validation_report",
        "text_heuristic",
        "1.0",
        "success",
        [],
        0,
        "2026-06-28T00:00:00+00:00",
    )
    chunk = DocumentChunk(
        "doc-1-chunk-001",
        "doc-1",
        "Heading",
        "Text",
        None,
        1,
        1,
        1,
        "data/documents/raw/doc.txt",
        "text_heuristic",
        "success",
    )
    citation = Citation(
        "cit-doc-1-001",
        "doc-1",
        "doc-1-chunk-001",
        "Heading",
        None,
        1,
        "data/documents/raw/doc.txt",
        "Text",
    )
    fact = ExtractedFact(
        "fact-1",
        "Label",
        "value",
        None,
        "doc-1",
        ["cit-doc-1-001"],
        "manual_curation",
        1.0,
        "notes",
        "2026-06-28T00:00:00+00:00",
    )
    card = EvidenceCard(
        "card-1",
        "Claim",
        "topic",
        ["fact-1"],
        ["cit-doc-1-001"],
        "supports",
        "pending",
        "note",
        [],
        "project-9199",
        "project",
        "2026-06-28T00:00:00+00:00",
    )
    finding = Finding(
        "finding-1",
        "AR_TEST",
        "High",
        "Description",
        "Gap",
        ["doc"],
        ["card-1"],
        "open",
        "pending",
        "note",
        "2026-06-28T00:00:00+00:00",
    )
    event = AuditEvent(
        "evt-20260628000000-00000000",
        "event",
        "subject",
        "project",
        "2026-06-28T00:00:00+00:00",
        "system",
        "carbon-dd-v1",
        "summary",
        {},
    )
    memo = ReviewerMemo(
        "memo-1",
        "9199",
        ["doc-1"],
        "2026-06-28T00:00:00+00:00",
        {"1. Project identity": "body"},
        ["AR_TEST"],
        ["Gap"],
        ["Q1"],
        ["evt-1"],
        "a" * 64,
    )
    memory = CaseMemory(
        "case-1",
        "9199",
        "project-9199",
        "2026-06-28T00:00:00+00:00",
        1,
        "b" * 64,
        [event.to_dict()],
    )
    assert parsed.document_id
    assert chunk.chunk_id
    assert citation.citation_id
    assert fact.fact_id
    assert card.card_id
    assert finding.finding_id
    assert memo.sections
    assert memory.timeline


def test_audit_event_serialises_to_json_and_back_cleanly():
    event = AuditEvent(
        "evt-20260628000000-00000000",
        "document_ingested",
        "doc-1",
        "document",
        "2026-06-28T00:00:00+00:00",
        "system",
        "carbon-dd-v1",
        "Document ingested",
        {"chunk_count": 1},
    )
    payload = json.loads(json.dumps(event.to_dict()))
    assert AuditEvent(**payload) == event


def test_reviewer_memo_sections_dict_is_non_empty():
    memo = ReviewerMemo(
        "memo-1",
        "9199",
        [],
        "2026-06-28T00:00:00+00:00",
        {"7. Disclaimer": "text"},
        [],
        [],
        [],
        [],
        "c" * 64,
    )
    assert memo.sections

