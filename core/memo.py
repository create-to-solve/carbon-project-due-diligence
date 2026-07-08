from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from core.audit import AuditLog
from core.models import EvidenceCard, Finding, ReviewerMemo

DISCLAIMER_TEXT = (
    "This memo is system-generated from structured registry data and manually curated "
    "evidence. It does not constitute a legal determination, investment advice, or "
    "eligibility certification. All findings require human review and verification "
    "against primary documents. The system records what is known, what is missing, "
    "and what requires judgment — it does not make the judgment."
)

NO_FINDINGS_QUESTION = (
    "Q1: No system-generated findings were produced for this project. Confirm the "
    "evidence base is complete and the correct rule set was applied."
)

NO_CITATION_NOTE = "No supporting evidence cited — requires manual review"

PROVISIONAL_NEXT_STEPS = (
    "[NEXT STEPS]\n"
    "1. Open the AI Proposals tab and review each AI-extracted candidate fact.\n"
    "2. Confirm, edit, or reject each proposal — nothing is accepted automatically.\n"
    "3. Click 'Update facts and rerun pipeline' to write the confirmed facts.\n"
    "4. Return here and regenerate this memo to produce the full findings assessment."
)


def memo_is_provisional(confirmed_fact_count: int | None) -> bool:
    """True when the project has zero confirmed facts.

    A memo built in this state must not present rule hits as authoritative
    'missing evidence' conclusions: the only reason anything looks missing is
    that no fact has been confirmed yet. Passing ``None`` means "unknown" and
    preserves the normal (non-provisional) memo for legacy callers.
    """
    return confirmed_fact_count is not None and confirmed_fact_count <= 0


def provisional_status_section(pending_proposal_count: int) -> str:
    return (
        "[STATUS — PROVISIONAL]\n"
        "STATUS: Provisional — no facts confirmed yet.\n"
        f"This project has {pending_proposal_count} AI-extracted proposals awaiting human "
        "confirmation. Findings and evidence assessment cannot be produced until facts are "
        "confirmed. This memo is a placeholder."
    )


def generic_reviewer_questions(findings: list[Finding]) -> list[str]:
    """Derive one reviewer question per finding when a project has no curated set."""
    if not findings:
        return [NO_FINDINGS_QUESTION]
    questions = []
    for index, finding in enumerate(findings, start=1):
        gap = (finding.evidence_gap or "").strip()
        suffix = f" (Needed: {gap})" if gap else ""
        questions.append(
            f"Q{index}: What evidence resolves {finding.flag_code}?{suffix}"
        )
    return questions


def reviewer_questions_for(
    project_record: dict[str, Any] | None, findings: list[Finding]
) -> list[str]:
    """Resolve reviewer questions from the project registry, else derive them.

    Preference order: a ``reviewer_questions`` list on the project registry entry,
    otherwise generic questions generated from the findings themselves.
    """
    custom = (project_record or {}).get("reviewer_questions")
    if custom:
        return list(custom)
    return generic_reviewer_questions(findings)


def build_memo(
    project_id: str,
    facts: dict[str, Any],
    evidence_cards: list[EvidenceCard],
    findings: list[Finding],
    audit_log: AuditLog,
    narratives: dict[str, str] | None = None,
    reviewer_questions: list[str] | None = None,
    project_record: dict[str, Any] | None = None,
    confirmed_fact_count: int | None = None,
    pending_proposal_count: int = 0,
) -> ReviewerMemo:
    audit_events = audit_log.read()
    provisional = memo_is_provisional(confirmed_fact_count)

    if provisional:
        # No confirmed facts: withhold findings, evidence assessment and AI
        # narratives. Identity still comes from the registry, which is valid
        # without any confirmed fact.
        sections = {
            "1. Project identity": _project_identity(facts, project_record),
            "2. Status": provisional_status_section(pending_proposal_count),
            "3. Next steps": PROVISIONAL_NEXT_STEPS,
            "4. Audit trail summary": _audit_summary(audit_events),
            "5. Disclaimer": DISCLAIMER_TEXT,
        }
        questions: list[str] = []
        open_findings: list[str] = []
        evidence_gaps: list[str] = []
    else:
        questions = (
            list(reviewer_questions)
            if reviewer_questions
            else generic_reviewer_questions(findings)
        )
        sections = {
            "1. Project identity": _project_identity(facts, project_record),
            "2. Material signals": _material_signals(findings),
            "3. Evidence summary": _evidence_summary(findings, evidence_cards, narratives),
            "4. Evidence gaps": _evidence_gaps(findings),
            "5. Reviewer questions": _reviewer_questions(questions),
            "6. Audit trail summary": _audit_summary(audit_events),
            "7. Disclaimer": DISCLAIMER_TEXT,
        }
        open_findings = [finding.flag_code for finding in findings if finding.review_status == "open"]
        evidence_gaps = [finding.evidence_gap for finding in findings if finding.evidence_gap]

    document_ids = sorted(
        {
            event.subject_id
            for event in audit_events
            if event.event_type == "document_ingested" and event.subject_type == "document"
        }
    )
    audit_event_ids = [event.event_id for event in audit_events]
    hash_payload = {
        "project_id": project_id,
        "document_ids": document_ids,
        "sections": sections,
        "open_findings": open_findings,
        "evidence_gaps": evidence_gaps,
        "reviewer_questions": questions,
        "audit_event_ids": audit_event_ids,
        "provisional": provisional,
    }
    content_hash = hashlib.sha256(_canonical_json(hash_payload).encode("utf-8")).hexdigest()
    return ReviewerMemo(
        memo_id=f"memo-project-{project_id}",
        project_id=project_id,
        document_ids=document_ids,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sections=sections,
        open_findings=open_findings,
        evidence_gaps=evidence_gaps,
        reviewer_questions=questions,
        audit_event_ids=audit_event_ids,
        content_hash=content_hash,
    )


def memo_to_markdown(memo: ReviewerMemo) -> str:
    lines = [
        f"# Carbon Market Due Diligence Memo — Project {memo.project_id}",
        "",
        f"Memo ID: {memo.memo_id}",
        f"Generated at: {memo.generated_at}",
        f"Content hash: {memo.content_hash}",
        "",
    ]
    for title, body in memo.sections.items():
        lines.extend([f"## {title}", "", body.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _first_present(*candidates: Any) -> str:
    """First non-empty candidate, else an honest 'not recorded' rather than None."""
    for candidate in candidates:
        if candidate not in (None, ""):
            return str(candidate)
    return "not recorded"


def _project_identity(
    facts: dict[str, Any], project_record: dict[str, Any] | None = None
) -> str:
    """Identity from the project registry first, falling back to confirmed facts.

    Registry data (title, host country, methodology) is legitimately available
    without any confirmed fact, so it must never render as 'None'.
    """
    record = project_record or {}
    return (
        "[STRUCTURED DATA]\n"
        f"Project ID: {_first_present(facts.get('project_id'), record.get('project_id'))}\n"
        f"Title: {_first_present(record.get('display_name'), facts.get('title'))}\n"
        f"Host country: {_first_present(record.get('host_country'), facts.get('host_country'))}\n"
        f"Methodology: {_first_present(record.get('methodology'), facts.get('methodology'))}\n"
        f"Activity scale: {_first_present(facts.get('activity_scale'))}\n"
        f"Crediting period: {_first_present(facts.get('crediting_period_start'))} to "
        f"{_first_present(facts.get('crediting_period_end'))}\n"
        f"Registration date: {_first_present(facts.get('registration_date'))}\n"
        f"Deregistration date: {_first_present(facts.get('deregistration_date'))}"
    )


def _material_signals(findings: list[Finding]) -> str:
    if not findings:
        return "[SYSTEM-GENERATED]\nNo material signals were generated by deterministic checks."
    lines = ["[SYSTEM-GENERATED]"]
    for finding in findings:
        lines.append(f"- {finding.severity} {finding.flag_code}: {finding.description}")
    return "\n".join(lines)


def _evidence_summary(
    findings: list[Finding],
    evidence_cards: list[EvidenceCard],
    narratives: dict[str, str] | None = None,
) -> str:
    cards_by_id = {card.card_id: card for card in evidence_cards}
    lines = ["[EVIDENCE CHAIN — cited]"]
    if not findings:
        lines.append("No findings require evidence-chain discussion.")
        return "\n\n".join(lines)
    for finding in findings:
        citations = _citations_for_finding(finding, cards_by_id)
        citation_text = (
            " ".join(f"[{citation_id}]" for citation_id in citations)
            if citations
            else f"[{NO_CITATION_NOTE}]"
        )
        if narratives and finding.flag_code in narratives:
            block = (
                f"{finding.flag_code} {citation_text}\n"
                f"{narratives[finding.flag_code].strip()}\n"
                "[AI-DRAFT — grounded in confirmed evidence, requires human review]"
            )
            lines.append(block)
            continue
        if finding.flag_code == "AR_DEREG_001":
            sentence = (
                f"The project status evidence {citation_text} records deregistration as a "
                "material event requiring human review of credit status and deregistration rationale."
            )
        elif finding.flag_code == "AR_ISS_GAP_001":
            sentence = (
                f"The monitoring and issuance evidence {citation_text} indicates the second "
                "monitoring period remained awaiting issuance request at deregistration."
            )
        else:
            sentence = (
                f"The validation report {citation_text} supports review of {finding.flag_code}: "
                f"{finding.description}"
            )
        lines.append(sentence)
    return "\n\n".join(lines)


def _evidence_gaps(findings: list[Finding]) -> str:
    lines = ["[GAPS]"]
    if not findings:
        lines.append("No open evidence gaps were generated by deterministic checks.")
        return "\n".join(lines)
    for finding in findings:
        docs = ", ".join(f"({index}) {doc.replace('_', ' ')}" for index, doc in enumerate(finding.required_documents, start=1))
        if finding.flag_code == "AR_ISS_GAP_001":
            lines.append(
                "AR_ISS_GAP_001 requires: (1) second monitoring period verification report, "
                "(2) deregistration notice with stated reason, (3) confirmation of credit serial status."
            )
        else:
            lines.append(f"{finding.flag_code} requires: {docs}.")
    return "\n".join(lines)


def _reviewer_questions(questions: list[str]) -> str:
    return "[REVIEWER QUESTIONS]\n" + "\n".join(questions)


def _audit_summary(events) -> str:
    if not events:
        return "[AUDIT TRAIL]\nNo audit events recorded."
    timestamps = sorted(event.timestamp for event in events)
    subject_ids = sorted({event.subject_id for event in events})
    documents = [
        event.subject_id for event in events if event.event_type == "document_ingested"
    ]
    curated_fact_events = [event for event in events if event.event_type == "facts_curated"]
    fact_count = sum(len(event.details.get("fact_ids", [])) for event in curated_fact_events)
    return (
        "[AUDIT TRAIL]\n"
        f"Total events: {len(events)}\n"
        f"Date range: {timestamps[0]} to {timestamps[-1]}\n"
        f"Subject IDs covered: {', '.join(subject_ids)}\n"
        f"Documents ingested: {', '.join(documents) if documents else 'none'}\n"
        f"Facts curated: {fact_count}"
    )


def _citations_for_finding(finding: Finding, cards_by_id: dict[str, EvidenceCard]) -> list[str]:
    citations: list[str] = []
    for card_id in finding.evidence_card_ids:
        card = cards_by_id.get(card_id)
        if card:
            citations.extend(card.citation_ids)
    return sorted(dict.fromkeys(citations))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))

