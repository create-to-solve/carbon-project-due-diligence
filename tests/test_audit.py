from core.audit import (
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
    emit_review_completed,
)
from core.models import AuditEvent


def test_audit_log_write_creates_file_and_read_returns_count(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    event = AuditEvent(
        "evt-20260628000000-00000000",
        "document_ingested",
        "doc-1",
        "document",
        "2026-06-28T00:00:00+00:00",
        "system",
        "carbon-dd-v1",
        "summary",
        {},
    )
    log.write(event)
    assert path.exists()
    assert len(log.read()) == 1


def test_subject_filter_returns_correct_subset(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    for subject in ["doc-1", "doc-2"]:
        log.write(
            AuditEvent(
                f"evt-20260628000000-{subject[-1] * 8}",
                "event",
                subject,
                "document",
                "2026-06-28T00:00:00+00:00",
                "system",
                "carbon-dd-v1",
                "summary",
                {},
            )
        )
    assert [event.subject_id for event in log.read("doc-2")] == ["doc-2"]


def test_two_writes_produce_two_lines_append_only(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    event = AuditEvent(
        "evt-20260628000000-11111111",
        "event",
        "doc-1",
        "document",
        "2026-06-28T00:00:00+00:00",
        "system",
        "carbon-dd-v1",
        "summary",
        {},
    )
    log.write(event)
    log.write(AuditEvent(**{**event.to_dict(), "event_id": "evt-20260628000000-22222222"}))
    assert len((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_all_emitters_produce_valid_event_types_and_unique_ids(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    events = [
        emit_document_ingested(log, "doc-1", "Title", 1, "success"),
        emit_chunks_created(log, "doc-1", ["chunk-1"]),
        emit_citations_created(log, "doc-1", ["cit-1"]),
        emit_facts_curated(log, "doc-1", ["fact-1"]),
        emit_evidence_card_created(log, "card-1", "topic", "supports"),
        emit_conflict_detected(log, "card-1", "card-2", "topic"),
        emit_finding_flagged(log, "9199", "finding-1", "AR_TEST", "High"),
        emit_memo_generated(log, "9199", "memo-1", 1, 1),
        emit_case_snapshot_taken(log, "9199", "case-1", "a" * 64, 8),
        emit_review_completed(log, "subject-1", "reviewer", "approve", "rationale"),
    ]
    assert [event.event_type for event in events] == [
        "document_ingested",
        "chunks_created",
        "citations_created",
        "facts_curated",
        "evidence_card_created",
        "conflict_detected",
        "finding_flagged",
        "memo_generated",
        "case_snapshot_taken",
        "review_completed",
    ]
    assert len({event.event_id for event in events}) == len(events)

