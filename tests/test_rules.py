from domain.project_9199 import PROJECT_9199_FACTS
from domain.rules_cdm import (
    check_additionality,
    check_deregistration,
    check_issuance_gap,
    check_permanence,
    run_all_checks,
)


def test_deregistration_fires_when_date_present():
    finding = check_deregistration({"deregistration_date": "2022-03-10"})
    assert finding is not None
    assert finding.flag_code == "AR_DEREG_001"


def test_issuance_gap_fires_when_awaiting_and_deregistered():
    finding = check_issuance_gap(
        {
            "second_issuance_status": "awaiting_issuance_request",
            "deregistration_date": "2022-03-10",
            "second_issuance_amount_cers": 374589,
        }
    )
    assert finding is not None
    assert finding.flag_code == "AR_ISS_GAP_001"


def test_additionality_does_not_fire_for_barrier_analysis():
    assert check_additionality({"additionality_approach": "barrier_analysis"}) is None


def test_permanence_does_not_fire_when_true():
    assert check_permanence({"permanence_risk_addressed": True}) is None


def test_run_all_checks_returns_list_never_raises():
    assert isinstance(run_all_checks(dict(PROJECT_9199_FACTS)), list)


def test_critical_findings_sort_before_high_findings():
    facts = dict(PROJECT_9199_FACTS)
    facts["additionality_approach"] = None
    findings = run_all_checks(facts)
    severities = [finding.severity for finding in findings]
    assert severities.index("Critical") < severities.index("High")

