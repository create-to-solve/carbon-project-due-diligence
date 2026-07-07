from __future__ import annotations

from datetime import datetime, timezone

from core.models import Finding

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def check_additionality(facts) -> Finding | None:
    allowed = {"investment_analysis", "barrier_analysis", "common_practice"}
    if facts.get("additionality_approach") in allowed:
        return None
    return _finding(
        "AR_ADD_001",
        "High",
        "Additionality approach is missing or not one of the accepted CDM A/R approaches.",
        "Need evidence of investment analysis, barrier analysis, or common-practice assessment.",
        ["validation_report", "registered_pdd"],
        ["card-2"],
    )


def check_baseline_methodology(facts) -> Finding | None:
    if facts.get("baseline_methodology_ref") is not None:
        return None
    return _finding(
        "AR_BASE_001",
        "High",
        "Baseline methodology reference is missing.",
        "Need registered methodology reference from validation or PDD materials.",
        ["registered_pdd", "validation_report"],
        ["card-1"],
    )


def check_monitoring_coverage(facts) -> Finding | None:
    if facts.get("monitoring_period_end") is not None:
        return None
    return _finding(
        "AR_MON_001",
        "Medium",
        "Monitoring period end date is missing.",
        "Need complete monitoring period coverage and end date.",
        ["second_monitoring_report"],
        ["card-6"],
    )


def check_validation(facts) -> Finding | None:
    if facts.get("validator_name") is not None:
        return None
    return _finding(
        "AR_VAL_001",
        "High",
        "Validator identity is missing.",
        "Need validation report naming the validating DOE.",
        ["validation_report"],
        [],
    )


def check_registration(facts) -> Finding | None:
    if facts.get("registration_date") is not None:
        return None
    return _finding(
        "AR_REG_001",
        "Medium",
        "Registration date is missing.",
        "Need CDM registration record.",
        ["registration_record"],
        [],
    )


def check_deregistration(facts) -> Finding | None:
    deregistration_date = facts.get("deregistration_date")
    if not deregistration_date:
        return None
    return _finding(
        "AR_DEREG_001",
        "Critical",
        (
            f"Project deregistered on {deregistration_date}. Credits issued "
            "under this project require verification of status."
        ),
        "Need deregistration notice and confirmation of credit status after deregistration.",
        ["deregistration_notice", "voluntary_cancellation_records"],
        ["card-4"],
    )


def check_issuance_gap(facts) -> Finding | None:
    if (
        facts.get("second_issuance_status") == "awaiting_issuance_request"
        and facts.get("deregistration_date") is not None
    ):
        amount = facts.get("second_issuance_amount_cers")
        return _finding(
            "AR_ISS_GAP_001",
            "Critical",
            (
                f"Second monitoring period credits ({amount} CERs, 2013-2020) "
                "remain unissued at time of deregistration. Recovery pathway is uncertain."
            ),
            "Need verification, issuance-pathway, and credit serial-status evidence.",
            ["second_monitoring_report", "verification_report_period_2", "deregistration_notice"],
            ["card-3", "card-6"],
        )
    return None


def check_permanence(facts) -> Finding | None:
    if facts.get("permanence_risk_addressed") is True:
        return None
    return _finding(
        "AR_PERM_001",
        "High",
        "Permanence risk treatment is missing or unresolved.",
        "Need evidence that reversal and permanence risks were addressed.",
        ["permanence_risk_assessment", "registered_pdd"],
        ["card-5"],
    )


def run_cdm_ar_checks(facts) -> list[Finding]:
    checks = [
        check_additionality,
        check_baseline_methodology,
        check_monitoring_coverage,
        check_validation,
        check_registration,
        check_deregistration,
        check_issuance_gap,
        check_permanence,
    ]
    findings = [finding for check in checks if (finding := check(facts)) is not None]
    return sorted(findings, key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.flag_code))


def run_all_checks(facts) -> list[Finding]:
    return run_cdm_ar_checks(facts)


def _finding(
    flag_code: str,
    severity: str,
    description: str,
    evidence_gap: str,
    required_documents: list[str],
    evidence_card_ids: list[str],
) -> Finding:
    return Finding(
        finding_id=f"finding-{flag_code.lower().replace('_', '-')}",
        flag_code=flag_code,
        severity=severity,
        description=description,
        evidence_gap=evidence_gap,
        required_documents=required_documents,
        evidence_card_ids=evidence_card_ids,
        review_status="open",
        reviewer_disposition="pending_human_review",
        reviewer_note="System-generated finding; not verified by a human reviewer.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

