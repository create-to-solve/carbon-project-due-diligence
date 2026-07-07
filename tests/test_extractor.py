from core.evidence import confirmed_proposals_to_facts, update_proposal_status
from core.extractor import build_proposals, extract_facts_from_chunk
from core.models import DocumentChunk, ParsedDocument


def _fact(label="label", value="value"):
    return {
        "label": label,
        "value": value,
        "unit": None,
        "claim_topic": "other",
        "confidence": 0.9,
        "evidence_quote": "value",
        "page_number": 1,
    }


def test_build_proposals():
    proposals = build_proposals([_fact("a", "1"), _fact("b", "2"), _fact("c", "3")], "project_9199")
    assert len(proposals) == 3
    assert all(proposal["status"] == "pending" for proposal in proposals)
    assert len({proposal["proposal_id"] for proposal in proposals}) == 3
    assert all(proposal["ai_extracted"] for proposal in proposals)
    assert all(proposal["human_edit"] is None for proposal in proposals)


def test_update_proposal_confirm():
    proposals = build_proposals([_fact()], "project_9199")
    updated = update_proposal_status(proposals, proposals[0]["proposal_id"], "confirm")
    assert updated[0]["status"] == "confirm"
    assert updated[0]["reviewed_at"]
    assert updated[0]["human_edit"] is None


def test_update_proposal_edit():
    proposals = build_proposals([_fact()], "project_9199")
    human_edit = {"label": "edited_label", "value": "edited_value"}
    updated = update_proposal_status(proposals, proposals[0]["proposal_id"], "edit", human_edit=human_edit)
    assert updated[0]["status"] == "edit"
    assert updated[0]["human_edit"] == human_edit


def test_update_proposal_reject():
    proposals = build_proposals([_fact()], "project_9199")
    updated = update_proposal_status(proposals, proposals[0]["proposal_id"], "reject")
    assert updated[0]["status"] == "reject"
    assert updated[0]["reviewed_at"]


def test_confirmed_proposals_to_facts():
    proposals = build_proposals([_fact("a", "1"), _fact("b", "2"), _fact("c", "3")], "project_9199")
    update_proposal_status(proposals, proposals[0]["proposal_id"], "confirm")
    update_proposal_status(proposals, proposals[1]["proposal_id"], "confirm")
    update_proposal_status(proposals, proposals[2]["proposal_id"], "reject")
    facts = confirmed_proposals_to_facts(proposals)
    assert len(facts) == 2
    assert facts[0]["extraction_method"] == "ai_extracted_confirmed"
    assert all(fact["value"] != "3" for fact in facts)


def test_extract_facts_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    document = ParsedDocument(
        "doc-1",
        "Title",
        "",
        "doc.pdf",
        "pdf",
        "9199",
        "validation_report",
        "pdfplumber",
        "1.0",
        "success",
        [],
        1,
        "2026-06-28T00:00:00+00:00",
    )
    chunk = DocumentChunk(
        "doc-1-page-001",
        "doc-1",
        "Heading",
        "Some project text",
        1,
        None,
        None,
        1,
        "doc.pdf",
        "pdfplumber",
        "success",
    )
    assert extract_facts_from_chunk(chunk, document, {}) == []
