from __future__ import annotations

from domain.rules_generic import (
    check_additionality_present,
    check_methodology_reference,
    check_validator_present,
    run_all_checks,
)


def test_methodology_fires_when_missing():
    finding = check_methodology_reference({})
    assert finding is not None
    assert finding.flag_code == "GEN_METH_001"
    assert finding.severity == "High"


def test_methodology_does_not_fire_when_present():
    assert check_methodology_reference({"methodology": "VM0044"}) is None
    assert check_methodology_reference({"baseline_methodology_ref": "AR-AM0004"}) is None


def test_validator_fires_when_missing():
    finding = check_validator_present({})
    assert finding is not None
    assert finding.flag_code == "GEN_VAL_001"
    assert finding.severity == "High"


def test_additionality_fires_when_missing():
    finding = check_additionality_present({})
    assert finding is not None
    assert finding.flag_code == "GEN_ADD_001"
    assert finding.severity == "High"


def test_no_findings_for_complete_facts():
    facts = {
        "title": "Test project",
        "host_country": "Testland",
        "methodology": "TEST-M v1",
        "baseline_methodology_ref": "TEST-M v1",
        "validator_name": "TestValidator",
        "crediting_period_start": "2024-01-01",
        "crediting_period_end": "2034-01-01",
        "additionality_approach": "barrier_analysis",
        "monitoring_plan_reference": "MP-1",
        "registration_date": "2024-06-01",
    }
    findings = run_all_checks(facts)
    assert all(finding.severity == "Low" for finding in findings)
