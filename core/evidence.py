from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import EvidenceCard, ExtractedFact


def load_facts(path: str) -> list[ExtractedFact]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ExtractedFact(**item) for item in payload]


def load_evidence_cards(path: str) -> list[EvidenceCard]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvidenceCard(**item) for item in payload]


def evidence_cards_from_records(records: list[dict[str, Any]]) -> list[EvidenceCard]:
    return [EvidenceCard(**record) for record in records]


def detect_conflicts(cards: list[EvidenceCard]) -> list[tuple[str, str, str]]:
    conflicts: list[tuple[str, str, str]] = []
    for left_index, left in enumerate(cards):
        for right in cards[left_index + 1 :]:
            if right.card_id in left.conflicts_with or left.card_id in right.conflicts_with:
                conflicts.append((left.card_id, right.card_id, left.claim_topic))
            elif (
                left.claim_topic == right.claim_topic
                and {left.evidence_role, right.evidence_role} == {"supports", "contradicts"}
            ):
                conflicts.append((left.card_id, right.card_id, left.claim_topic))
    return conflicts


def load_proposals(proposals_path: str) -> list[dict]:
    path = Path(proposals_path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_proposals(proposals: list[dict], proposals_path: str) -> None:
    path = Path(proposals_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposals, indent=2, sort_keys=True), encoding="utf-8")


def update_proposal_status(
    proposals: list[dict],
    proposal_id: str,
    action: str,
    human_edit: dict | None = None,
    audit_note: str | None = None,
) -> list[dict]:
    for proposal in proposals:
        if proposal.get("proposal_id") != proposal_id:
            continue
        proposal["status"] = action
        proposal["reviewer_action"] = action
        proposal["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        if action == "edit":
            proposal["human_edit"] = human_edit
        if audit_note is not None:
            proposal["audit_note"] = audit_note
        break
    return proposals


def confirmed_proposals_to_facts(proposals: list[dict]) -> list[dict]:
    facts = []
    for proposal in proposals:
        status = proposal.get("status")
        if status == "confirm":
            source = dict(proposal.get("ai_extracted") or {})
            extraction_method = "ai_extracted_confirmed"
        elif status == "edit":
            source = dict(proposal.get("human_edit") or {})
            extraction_method = "ai_extracted_edited"
        else:
            continue
        proposal_id = proposal.get("proposal_id", "unknown")
        evidence_quote = source.get("evidence_quote")
        notes = source.get("notes") or "AI-extracted proposal confirmed by human reviewer."
        if evidence_quote:
            notes = f"{notes} Evidence quote: {evidence_quote}"
        facts.append(
            {
                "fact_id": f"fact-{proposal_id}",
                "label": source.get("label", ""),
                "value": source.get("value", ""),
                "unit": source.get("unit"),
                "source_document_id": source.get("source_document_id") or source.get("document_id", ""),
                "citation_ids": source.get("citation_ids", []),
                "extraction_method": extraction_method,
                "confidence": source.get("confidence", 1.0),
                "notes": notes,
                "extracted_at": source.get("extracted_at") or datetime.now(timezone.utc).isoformat(),
                "search_terms": source.get("search_terms", []),
                "matched_terms": source.get("matched_terms", []),
            }
        )
    return facts
