from __future__ import annotations

from datetime import datetime, timezone

from core.audit import AuditLog
from core.memo import DISCLAIMER_TEXT, build_memo, memo_is_provisional
from domain.rules_generic import run_all_checks as run_generic_checks
from scripts.build_review_pack import build_html

# Mirrors Project 0547: registry knows the identity, 196 proposals extracted,
# zero facts confirmed. Every "missing" rule hit is an artifact of non-confirmation.
PROJECT_0547_RECORD = {
    "project_id": "project_0547_reforestation_guangxi_watershed",
    "display_name": "Facilitating Reforestation for Guangxi Watershed Management",
    "host_country": "China",
    "methodology": "AR-AM0001 ver. 2",
    "methodology_type": "cdm_ar",
    "status": "unknown",
}

PENDING_PROPOSALS = 196


def _identity_only_facts() -> dict:
    """What the app passes when nothing has been confirmed."""
    return {"project_id": PROJECT_0547_RECORD["project_id"]}


def _findings_from_no_confirmed_facts():
    return run_generic_checks(_identity_only_facts())


def _log(tmp_path) -> AuditLog:
    return AuditLog(str(tmp_path / "audit.jsonl"))


# --- memo_is_provisional ---------------------------------------------------

def test_memo_is_provisional_only_at_zero_confirmed_facts():
    assert memo_is_provisional(0) is True
    assert memo_is_provisional(1) is False
    assert memo_is_provisional(None) is False  # unknown -> legacy normal memo


# --- Step 2: provisional memo ----------------------------------------------

def test_zero_confirmed_facts_produces_provisional_memo(tmp_path):
    findings = _findings_from_no_confirmed_facts()
    assert findings, "sanity: rules do fire when nothing is confirmed"

    memo = build_memo(
        PROJECT_0547_RECORD["project_id"],
        _identity_only_facts(),
        [],
        findings,
        _log(tmp_path),
        narratives={"GEN_ADD_001": "Additionality is entirely absent from the record."},
        project_record=PROJECT_0547_RECORD,
        confirmed_fact_count=0,
        pending_proposal_count=PENDING_PROPOSALS,
    )

    assert list(memo.sections) == [
        "1. Project identity",
        "2. Status",
        "3. Next steps",
        "4. Audit trail summary",
        "5. Disclaimer",
    ]
    body = "\n".join(memo.sections.values())
    # No "missing evidence" conclusions, no findings, no AI narratives.
    assert "Material signals" not in memo.sections
    assert "GEN_ADD_001" not in body
    assert "GEN_METH_001" not in body
    assert "AI-DRAFT" not in body
    assert "Additionality is entirely absent" not in body
    assert memo.open_findings == []
    assert memo.evidence_gaps == []
    assert memo.reviewer_questions == []
    # Provisional status is stated plainly, with the pending count and disclaimer.
    status = memo.sections["2. Status"]
    assert "STATUS: Provisional" in status
    assert str(PENDING_PROPOSALS) in status
    assert "placeholder" in status
    assert DISCLAIMER_TEXT in memo.sections["5. Disclaimer"]
    assert "AI Proposals" in memo.sections["3. Next steps"]


def test_confirmed_facts_produce_a_normal_findings_memo(tmp_path):
    findings = _findings_from_no_confirmed_facts()
    memo = build_memo(
        PROJECT_0547_RECORD["project_id"],
        _identity_only_facts(),
        [],
        findings,
        _log(tmp_path),
        project_record=PROJECT_0547_RECORD,
        confirmed_fact_count=3,
        pending_proposal_count=0,
    )
    assert list(memo.sections) == [
        "1. Project identity",
        "2. Material signals",
        "3. Evidence summary",
        "4. Evidence gaps",
        "5. Reviewer questions",
        "6. Audit trail summary",
        "7. Disclaimer",
    ]
    assert "GEN_METH_001" in memo.sections["2. Material signals"]
    assert memo.open_findings


def test_provisional_memo_ignores_narratives_even_when_supplied(tmp_path):
    memo = build_memo(
        "p",
        {"project_id": "p"},
        [],
        _findings_from_no_confirmed_facts(),
        _log(tmp_path),
        narratives={"GEN_VAL_001": "No validator was ever appointed."},
        confirmed_fact_count=0,
    )
    assert "No validator was ever appointed" not in "\n".join(memo.sections.values())


# --- Step 3: identity from the registry, never None ------------------------

def test_identity_reads_registry_not_none(tmp_path):
    memo = build_memo(
        PROJECT_0547_RECORD["project_id"],
        _identity_only_facts(),
        [],
        [],
        _log(tmp_path),
        project_record=PROJECT_0547_RECORD,
        confirmed_fact_count=0,
    )
    identity = memo.sections["1. Project identity"]
    assert "Facilitating Reforestation for Guangxi Watershed Management" in identity
    assert "China" in identity
    assert "AR-AM0001 ver. 2" in identity
    assert "None" not in identity
    assert "[STRUCTURED DATA]" in identity


def test_identity_falls_back_to_facts_when_registry_lacks_field(tmp_path):
    memo = build_memo(
        "p",
        {"project_id": "p", "host_country": "Peru", "registration_date": "2020-01-01"},
        [],
        [],
        _log(tmp_path),
        project_record={"display_name": "Registry Title"},
        confirmed_fact_count=1,
    )
    identity = memo.sections["1. Project identity"]
    assert "Registry Title" in identity  # registry wins
    assert "Peru" in identity  # falls back to facts
    assert "2020-01-01" in identity
    assert "None" not in identity


def test_identity_without_any_source_says_not_recorded(tmp_path):
    memo = build_memo("p", {"project_id": "p"}, [], [], _log(tmp_path), confirmed_fact_count=1)
    identity = memo.sections["1. Project identity"]
    assert "not recorded" in identity
    assert "None" not in identity


# --- Step 4: review pack guard ---------------------------------------------

def _pack_html(provisional: bool, critical_flags: list[str], narratives: dict) -> str:
    return build_html(
        project_id=PROJECT_0547_RECORD["project_id"],
        facts={
            "project_id": PROJECT_0547_RECORD["project_id"],
            "title": PROJECT_0547_RECORD["display_name"],
            "host_country": PROJECT_0547_RECORD["host_country"],
            "methodology": PROJECT_0547_RECORD["methodology"],
            "limitations": [],
        },
        cards=[],
        audit_events=[],
        snapshot={},
        narratives=narratives,
        critical_flags=critical_flags,
        reviewer_questions=[],
        generated_at=datetime.now(timezone.utc),
        provisional=provisional,
        pending_proposal_count=PENDING_PROPOSALS,
    )


def test_review_pack_provisional_has_no_critical_signals():
    html = _pack_html(
        provisional=True,
        critical_flags=[],
        narratives={"GEN_ADD_001": "Additionality is entirely absent."},
    )
    assert "Critical Signals" not in html
    assert "Additionality is entirely absent" not in html
    assert "Evidence Gaps" not in html
    assert "STATUS: Provisional" in html
    assert str(PENDING_PROPOSALS) in html
    assert DISCLAIMER_TEXT in html
    # Identity is still legitimately shown.
    assert "Facilitating Reforestation for Guangxi Watershed Management" in html


def test_review_pack_non_provisional_still_shows_critical_signals():
    html = _pack_html(provisional=False, critical_flags=["AR_DEREG_001"], narratives={})
    assert "Critical Signals" in html
    assert "AR_DEREG_001" in html
    assert "STATUS: Provisional" not in html
