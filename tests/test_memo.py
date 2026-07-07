from core.audit import AuditLog
from core.evidence import load_evidence_cards
from core.memo import (
    DISCLAIMER_TEXT,
    NO_CITATION_NOTE,
    build_memo,
    reviewer_questions_for,
)
from core.models import AuditEvent
from domain.project_9199 import PROJECT_9199_FACTS
from domain.rules_cdm import run_all_checks
from domain.rules_generic import run_all_checks as run_generic_checks


def test_memo_has_all_seven_sections(tmp_path):
    memo = _memo(tmp_path)
    assert list(memo.sections) == [
        "1. Project identity",
        "2. Material signals",
        "3. Evidence summary",
        "4. Evidence gaps",
        "5. Reviewer questions",
        "6. Audit trail summary",
        "7. Disclaimer",
    ]


def test_material_signals_non_empty_for_project_9199(tmp_path):
    memo = _memo(tmp_path)
    assert "AR_DEREG_001" in memo.sections["2. Material signals"]
    assert "AR_ISS_GAP_001" in memo.sections["2. Material signals"]


def test_disclaimer_text_present_verbatim(tmp_path):
    memo = _memo(tmp_path)
    assert DISCLAIMER_TEXT in memo.sections["7. Disclaimer"]


def test_content_hash_is_64_char_hex(tmp_path):
    memo = _memo(tmp_path)
    assert len(memo.content_hash) == 64
    int(memo.content_hash, 16)


def test_same_inputs_produce_same_content_hash(tmp_path):
    memo_a = _memo(tmp_path / "a")
    memo_b = _memo(tmp_path / "b")
    assert memo_a.content_hash == memo_b.content_hash


def _generic_facts():
    return {
        "project_id": "project_test_vcs_001",
        "title": "Test VCS Project — Generic Demo",
        "host_country": "Indonesia",
    }


def _generic_memo(tmp_path):
    facts = _generic_facts()
    findings = run_generic_checks(facts)
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    return build_memo("project_test_vcs_001", facts, [], findings, log)


def test_non_9199_memo_has_no_9199_reviewer_questions(tmp_path):
    questions = _generic_memo(tmp_path).sections["5. Reviewer questions"]
    assert "deregistration in March 2022" not in questions
    assert "1,257,195" not in questions
    assert "What evidence resolves" in questions


def test_generic_findings_do_not_cite_9199_validation_report(tmp_path):
    summary = _generic_memo(tmp_path).sections["3. Evidence summary"]
    assert "cit-doc-9199-val-001" not in summary
    assert NO_CITATION_NOTE in summary


def test_9199_findings_still_cite_their_evidence_cards(tmp_path):
    summary = _memo(tmp_path).sections["3. Evidence summary"]
    assert NO_CITATION_NOTE not in summary
    assert "cit-doc-9199-mon2-001" in summary


def test_reviewer_questions_for_prefers_registry_field():
    record = {"reviewer_questions": ["Q1: custom curated question"]}
    assert reviewer_questions_for(record, []) == ["Q1: custom curated question"]


def test_reviewer_questions_for_derives_from_findings_when_absent():
    findings = run_generic_checks(_generic_facts())
    questions = reviewer_questions_for({}, findings)
    assert questions
    assert all("What evidence resolves" in question for question in questions)


def test_9199_reviewer_questions_preserved_when_supplied(tmp_path):
    facts = dict(PROJECT_9199_FACTS)
    cards_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "evidence" / "project_9199_cards.json"
    cards = load_evidence_cards(str(cards_path))
    findings = run_all_checks(facts)
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    custom = [
        "Q1: What was the stated reason for deregistration in March 2022, and was it voluntary or regulatory?",
    ]
    memo = build_memo(
        facts["project_id"], facts, cards, findings, log, reviewer_questions=custom
    )
    assert "deregistration in March 2022" in memo.sections["5. Reviewer questions"]


def _memo(tmp_path):
    facts = dict(PROJECT_9199_FACTS)
    cards_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "evidence" / "project_9199_cards.json"
    cards = load_evidence_cards(str(cards_path))
    findings = run_all_checks(facts)
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    for index, finding in enumerate(findings, start=1):
        log.write(
            AuditEvent(
                f"evt-2026062800000{index}-0000000{index}",
                "finding_flagged",
                finding.finding_id,
                "finding",
                f"2026-06-28T00:00:0{index}+00:00",
                "system",
                "carbon-dd-v1",
                f"{finding.severity} finding flagged: {finding.flag_code}",
                {
                    "project_id": facts["project_id"],
                    "finding_id": finding.finding_id,
                    "flag_code": finding.flag_code,
                    "severity": finding.severity,
                },
            )
        )
    return build_memo(facts["project_id"], facts, cards, findings, log)
