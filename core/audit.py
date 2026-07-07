from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import AuditEvent

LAB_ORIGIN = "carbon-dd-v1"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_event_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"evt-{stamp}-{uuid.uuid4().hex[:8]}"


def _event(
    event_type: str,
    subject_id: str,
    subject_type: str,
    actor: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=generate_event_id(),
        event_type=event_type,
        subject_id=subject_id,
        subject_type=subject_type,
        timestamp=now_utc_iso(),
        actor=actor,
        lab_origin=LAB_ORIGIN,
        summary=summary,
        details=details or {},
    )


class AuditLog:
    def __init__(self, log_path: str):
        self.log_path = log_path

    def write(self, event: AuditEvent) -> AuditEvent:
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    def read(self, subject_id: str | None = None) -> list[AuditEvent]:
        path = Path(self.log_path)
        if not path.exists():
            return []
        events: list[AuditEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if subject_id is None or payload.get("subject_id") == subject_id:
                    events.append(AuditEvent(**payload))
        return events

    def get_subject_history(self, subject_id: str) -> list[AuditEvent]:
        matched = []
        for event in self.read():
            if event.subject_id == subject_id or _details_contains(event.details, subject_id):
                matched.append(event)
        return sorted(matched, key=lambda event: event.timestamp)


def _details_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, list):
        return any(_details_contains(item, needle) for item in value)
    if isinstance(value, dict):
        return any(_details_contains(item, needle) for item in value.values())
    return False


def emit_document_ingested(
    log: AuditLog, document_id: str, title: str, chunk_count: int, parse_status: str
) -> AuditEvent:
    event = _event(
        "document_ingested",
        document_id,
        "document",
        "system",
        f"Document ingested: {title}",
        {"document_id": document_id, "title": title, "chunk_count": chunk_count, "parse_status": parse_status},
    )
    return log.write(event)


def emit_chunks_created(log: AuditLog, document_id: str, chunk_ids: list[str]) -> AuditEvent:
    event = _event(
        "chunks_created",
        document_id,
        "document",
        "system",
        f"{len(chunk_ids)} chunks created for {document_id}",
        {"document_id": document_id, "chunk_ids": chunk_ids},
    )
    return log.write(event)


def emit_citations_created(log: AuditLog, document_id: str, citation_ids: list[str]) -> AuditEvent:
    event = _event(
        "citations_created",
        document_id,
        "document",
        "system",
        f"{len(citation_ids)} citations created for {document_id}",
        {"document_id": document_id, "citation_ids": citation_ids},
    )
    return log.write(event)


def emit_facts_curated(log: AuditLog, document_id: str, fact_ids: list[str]) -> AuditEvent:
    event = _event(
        "facts_curated",
        document_id,
        "document",
        "system",
        f"{len(fact_ids)} facts curated from {document_id}",
        {"document_id": document_id, "fact_ids": fact_ids},
    )
    return log.write(event)


def emit_evidence_card_created(
    log: AuditLog, card_id: str, claim_topic: str, evidence_role: str
) -> AuditEvent:
    event = _event(
        "evidence_card_created",
        card_id,
        "evidence",
        "system",
        f"Evidence card {card_id} created for {claim_topic}",
        {"card_id": card_id, "claim_topic": claim_topic, "evidence_role": evidence_role},
    )
    return log.write(event)


def emit_conflict_detected(
    log: AuditLog, card_a_id: str, card_b_id: str, claim_topic: str
) -> AuditEvent:
    event = _event(
        "conflict_detected",
        card_a_id,
        "evidence",
        "system",
        f"Potential conflict detected for {claim_topic}",
        {"card_a_id": card_a_id, "card_b_id": card_b_id, "claim_topic": claim_topic},
    )
    return log.write(event)


def emit_finding_flagged(
    log: AuditLog, project_id: str, finding_id: str, flag_code: str, severity: str
) -> AuditEvent:
    event = _event(
        "finding_flagged",
        finding_id,
        "finding",
        "system",
        f"{severity} finding flagged: {flag_code}",
        {"project_id": project_id, "finding_id": finding_id, "flag_code": flag_code, "severity": severity},
    )
    return log.write(event)


def emit_memo_generated(
    log: AuditLog, project_id: str, memo_id: str, finding_count: int, open_gap_count: int
) -> AuditEvent:
    event = _event(
        "memo_generated",
        memo_id,
        "memo",
        "system",
        f"Reviewer memo generated for project {project_id}",
        {"project_id": project_id, "memo_id": memo_id, "finding_count": finding_count, "open_gap_count": open_gap_count},
    )
    return log.write(event)


def emit_case_snapshot_taken(
    log: AuditLog, project_id: str, case_id: str, content_hash: str, event_count: int
) -> AuditEvent:
    event = _event(
        "case_snapshot_taken",
        case_id,
        "case",
        "system",
        f"Case memory snapshot taken for project {project_id}",
        {"project_id": project_id, "case_id": case_id, "content_hash": content_hash, "event_count": event_count},
    )
    return log.write(event)


def emit_review_completed(
    log: AuditLog, subject_id: str, reviewer_id: str, verdict: str, rationale: str
) -> AuditEvent:
    event = _event(
        "review_completed",
        subject_id,
        "review",
        "human",
        f"Review completed by {reviewer_id}: {verdict}",
        {"reviewer_id": reviewer_id, "verdict": verdict, "rationale": rationale},
    )
    return log.write(event)


def emit_ai_extraction_completed(
    log: AuditLog, document_id: str, proposal_count: int, chunks_sent: int, model: str
) -> AuditEvent:
    event = _event(
        "ai_extraction_completed",
        document_id,
        "document",
        "system",
        f"AI extraction completed for {document_id}: {proposal_count} proposals",
        {"proposal_count": proposal_count, "chunks_sent": chunks_sent, "model": model},
    )
    return log.write(event)


def emit_proposal_confirmed(
    log: AuditLog, proposal_id: str, label: str, value: str, claim_topic: str
) -> AuditEvent:
    event = _event(
        "proposal_confirmed",
        proposal_id,
        "proposal",
        "human",
        f"Proposal confirmed: {label}",
        {"label": label, "value": value, "claim_topic": claim_topic},
    )
    return log.write(event)


def emit_proposal_edited(
    log: AuditLog, proposal_id: str, original_label: str, edited_label: str
) -> AuditEvent:
    event = _event(
        "proposal_edited",
        proposal_id,
        "proposal",
        "human",
        f"Proposal edited: {original_label} -> {edited_label}",
        {"original_label": original_label, "edited_label": edited_label},
    )
    return log.write(event)


def emit_proposal_rejected(
    log: AuditLog, proposal_id: str, label: str, claim_topic: str
) -> AuditEvent:
    event = _event(
        "proposal_rejected",
        proposal_id,
        "proposal",
        "human",
        f"Proposal rejected: {label}",
        {"label": label, "claim_topic": claim_topic, "reason": "human_rejected"},
    )
    return log.write(event)


def emit_narratives_generated(
    log: AuditLog, project_id: str, finding_count: int, model: str, narratives_path: str
) -> AuditEvent:
    event = _event(
        "narratives_generated",
        project_id,
        "project",
        "system",
        f"AI narratives generated for {finding_count} findings on project {project_id}",
        {
            "finding_count": finding_count,
            "model": model,
            "narratives_path": narratives_path,
        },
    )
    return log.write(event)


def emit_facts_updated_from_proposals(
    log: AuditLog, project_id: str, confirmed_count: int, edited_count: int, total_facts: int
) -> AuditEvent:
    event = _event(
        "facts_updated_from_proposals",
        project_id,
        "project",
        "human",
        f"Facts updated from AI proposals for {project_id}",
        {
            "confirmed_count": confirmed_count,
            "edited_count": edited_count,
            "total_facts_after_merge": total_facts,
        },
    )
    return log.write(event)
