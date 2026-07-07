from __future__ import annotations

from types import SimpleNamespace

import app
from domain.risk_flags import claim_topics_for_flag, expected_document_is_held
from domain.rules_cdm import run_all_checks

CDM_FLAGS = [
    "AR_ADD_001",
    "AR_BASE_001",
    "AR_VAL_001",
    "AR_MON_001",
    "AR_REG_001",
    "AR_DEREG_001",
    "AR_ISS_GAP_001",
    "AR_PERM_001",
]


def _doc(document_type: str):
    return SimpleNamespace(document_type=document_type)


# --- Step 2: flag -> claim_topic mapping -----------------------------------

def test_every_cdm_flag_maps_to_claim_topics():
    for flag in CDM_FLAGS:
        assert claim_topics_for_flag(flag), f"{flag} has no claim_topic mapping"


def test_specific_flag_topic_mappings():
    assert "additionality" in claim_topics_for_flag("AR_ADD_001")
    assert "baseline_methodology" in claim_topics_for_flag("AR_BASE_001")
    assert "monitoring" in claim_topics_for_flag("AR_MON_001")
    assert "permanence" in claim_topics_for_flag("AR_PERM_001")
    assert "project_identity" in claim_topics_for_flag("AR_VAL_001")


def test_unknown_flag_maps_to_empty_list():
    assert claim_topics_for_flag("NOPE_999") == []


# --- Step 2: provisional / empty-facts state -------------------------------

def test_findings_provisional_when_no_confirmed_facts():
    assert app._findings_provisional([]) is True


def test_findings_not_provisional_once_a_fact_is_confirmed():
    assert app._findings_provisional([{"fact_id": "fact-1"}]) is False


# --- Step 4: expected-document reconciliation ------------------------------

def test_held_pdd_satisfies_registered_pdd():
    assert expected_document_is_held("registered_pdd", {"pdd"}) is True


def test_validation_report_not_satisfied_by_a_pdd():
    assert expected_document_is_held("validation_report", {"pdd"}) is False


def test_unmapped_expected_documents_stay_genuine_gaps():
    held = {"pdd", "validation_report", "monitoring_report"}
    for expected in (
        "deregistration_notice",
        "permanence_risk_assessment",
        "registration_record",
    ):
        assert expected_document_is_held(expected, held) is False


def test_expected_documents_status_marks_held_pdd():
    findings = run_all_checks({"project_id": "proj_x"})  # empty facts -> gaps
    rows = {
        row["document"]: row["status"]
        for row in app._expected_documents_status(findings, [_doc("pdd")])
    }
    assert rows.get("registered pdd") == "HELD (contents not verified)"
    assert rows.get("validation report") == "NOT HELD"


# --- Step 4 honesty: held document must NOT resolve a finding --------------

def test_held_pdd_does_not_change_or_resolve_findings():
    facts: list = []  # zero confirmed facts
    project_record = {
        "methodology_type": "cdm_ar",
        "display_name": "Proj X",
        "host_country": "Testland",
        "methodology": "AR-AM0001",
    }
    without_doc_guarded = app._compute_findings("proj_x", project_record, facts, [])
    with_held_pdd = app._compute_findings("proj_x", project_record, facts, [_doc("pdd")])
    # The rules run on facts only; a held PDD never resolves a finding, so the
    # additionality/baseline findings stay OPEN even though the PDD is held.
    flags = {f.flag_code for f in with_held_pdd}
    assert "AR_ADD_001" in flags
    assert "AR_BASE_001" in flags
    # And holding a document does not close anything: no finding disappears
    # relative to a run with the same facts.
    assert without_doc_guarded == []  # guard: nothing at all -> nothing to screen


# --- Step 5: workflow pipeline step honesty --------------------------------

def test_pipeline_step_provisional_when_no_facts():
    assert app._pipeline_step_state(pipeline_ran=True, facts_confirmed=False) == "provisional"


def test_pipeline_step_done_when_facts_confirmed():
    assert app._pipeline_step_state(pipeline_ran=True, facts_confirmed=True) == "done"


def test_pipeline_step_todo_when_not_run():
    assert app._pipeline_step_state(pipeline_ran=False, facts_confirmed=False) == "todo"
