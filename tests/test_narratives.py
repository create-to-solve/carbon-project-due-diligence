from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from core.audit import AuditLog
from core.evidence import load_evidence_cards
from core.extractor import (
    MODEL as EXTRACTOR_MODEL,
    NARRATIVE_FALLBACK,
    generate_all_narratives,
)
from core.memo import build_memo
from core.models import Finding
from domain.project_9199 import PROJECT_9199_FACTS
from domain.rules_cdm import run_all_checks


def _finding(flag_code: str = "AR_DEREG_001", finding_id: str = "find-1") -> Finding:
    return Finding(
        finding_id=finding_id,
        flag_code=flag_code,
        severity="Critical",
        description="Test description.",
        evidence_gap="Test gap.",
        required_documents=["validation_report"],
        evidence_card_ids=[],
        review_status="open",
        reviewer_disposition="awaiting_review",
        reviewer_note="",
        created_at="2026-06-28T00:00:00+00:00",
    )


def _fact(fact_id: str, topic: str) -> dict:
    return {
        "fact_id": fact_id,
        "label": f"label-{fact_id}",
        "value": f"value-{fact_id}",
        "unit": None,
        "claim_topic": topic,
        "confidence": 0.9,
        "citation_ids": [],
        "source_document_id": "doc-9199-val",
    }


def test_generate_all_narratives_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    findings = [_finding("AR_DEREG_001", "f-1"), _finding("AR_ISS_GAP_001", "f-2")]
    with patch("core.extractor.OpenAI", create=True) as mock_client:
        result = generate_all_narratives(
            findings=findings,
            facts=[],
            evidence_cards=[],
            chunks_by_document={},
            project_context=dict(PROJECT_9199_FACTS),
        )
    assert mock_client.called is False
    assert set(result.keys()) == {"AR_DEREG_001", "AR_ISS_GAP_001"}
    for value in result.values():
        assert value == NARRATIVE_FALLBACK


def test_narratives_file_structure(tmp_path):
    payload = {
        "project_id": "project_9199",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": EXTRACTOR_MODEL,
        "narratives": {
            "AR_DEREG_001": "Deregistration paragraph text.",
            "AR_ISS_GAP_001": "Issuance gap paragraph text.",
        },
    }
    path = tmp_path / "project_9199_narratives.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["project_id"] == "project_9199"
    assert loaded["model"] == EXTRACTOR_MODEL
    assert "generated_at" in loaded
    assert "narratives" in loaded
    assert isinstance(loaded["narratives"]["AR_DEREG_001"], str)
    assert isinstance(loaded["narratives"]["AR_ISS_GAP_001"], str)


def test_memo_with_narratives(tmp_path):
    facts = dict(PROJECT_9199_FACTS)
    cards_path = Path(__file__).resolve().parents[1] / "data" / "evidence" / "project_9199_cards.json"
    cards = load_evidence_cards(str(cards_path))
    findings = run_all_checks(facts)
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    narratives = {
        "AR_DEREG_001": "This is a synthetic deregistration narrative paragraph for testing.",
    }
    memo = build_memo(facts["project_id"], facts, cards, findings, log, narratives)
    summary = memo.sections["3. Evidence summary"]
    assert "This is a synthetic deregistration narrative paragraph for testing." in summary
    assert "[AI-DRAFT — grounded in confirmed evidence, requires human review]" in summary


def test_memo_without_narratives(tmp_path):
    facts = dict(PROJECT_9199_FACTS)
    cards_path = Path(__file__).resolve().parents[1] / "data" / "evidence" / "project_9199_cards.json"
    cards = load_evidence_cards(str(cards_path))
    findings = run_all_checks(facts)
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    memo = build_memo(facts["project_id"], facts, cards, findings, log, None)
    full_text = "\n".join(memo.sections.values())
    assert "[AI-DRAFT" not in full_text
    assert "AR_DEREG_001" in memo.sections["2. Material signals"]


def test_narrative_topic_mapping(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    finding = _finding("AR_DEREG_001", "find-dereg")
    facts = [
        _fact("f-1", "deregistration"),
        _fact("f-2", "project_identity"),
        _fact("f-3", "cancellations"),
        _fact("f-4", "baseline_methodology"),
        _fact("f-5", "additionality"),
    ]

    captured: dict = {}

    def fake_generate(
        finding_arg, relevant_facts, relevant_cards, relevant_chunks, project_context
    ):
        captured["facts"] = relevant_facts
        captured["cards"] = relevant_cards
        return "stub-narrative"

    with patch("core.extractor.generate_finding_narrative", side_effect=fake_generate):
        result = generate_all_narratives(
            findings=[finding],
            facts=facts,
            evidence_cards=[],
            chunks_by_document={},
            project_context=dict(PROJECT_9199_FACTS),
        )

    assert result == {"AR_DEREG_001": "stub-narrative"}
    selected_ids = {fact["fact_id"] for fact in captured["facts"]}
    assert selected_ids == {"f-1", "f-2", "f-3"}
    excluded_ids = {"f-4", "f-5"}
    assert selected_ids.isdisjoint(excluded_ids)
