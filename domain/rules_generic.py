from __future__ import annotations

from datetime import datetime, timezone

from core.models import Finding

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def check_project_title(facts) -> Finding | None:
    if not _missing(facts.get("title")):
        return None
    return _finding(
        "GEN_TITLE_001",
        "Low",
        "Project title is missing.",
        "Project title is required for identification.",
        ["registered_pdd", "project_description"],
    )


def check_host_country(facts) -> Finding | None:
    if not _missing(facts.get("host_country")):
        return None
    return _finding(
        "GEN_COUNTRY_001",
        "Low",
        "Host country is missing.",
        "Host country is required for jurisdictional review.",
        ["registered_pdd", "project_description"],
    )


def check_methodology_reference(facts) -> Finding | None:
    if not _missing(facts.get("methodology")) or not _missing(facts.get("baseline_methodology_ref")):
        return None
    return _finding(
        "GEN_METH_001",
        "High",
        "No methodology reference found. Carbon projects must apply an approved methodology.",
        "Need an approved methodology reference from the project documentation.",
        ["registered_pdd", "validation_report"],
    )


def check_validator_present(facts) -> Finding | None:
    if not _missing(facts.get("validator_name")):
        return None
    return _finding(
        "GEN_VAL_001",
        "High",
        "No validator identified. Third-party validation is required for carbon credit issuance.",
        "Need validation report naming the validating body.",
        ["validation_report"],
    )


def check_crediting_period(facts) -> Finding | None:
    if not _missing(facts.get("crediting_period_start")) and not _missing(facts.get("crediting_period_end")):
        return None
    return _finding(
        "GEN_CRED_001",
        "Medium",
        "Crediting period not fully defined.",
        "Need both crediting period start and end dates.",
        ["registered_pdd", "validation_report"],
    )


def check_additionality_present(facts) -> Finding | None:
    if not _missing(facts.get("additionality_approach")):
        return None
    return _finding(
        "GEN_ADD_001",
        "High",
        "No additionality approach identified. All carbon projects must demonstrate additionality.",
        "Need evidence of an accepted additionality demonstration approach.",
        ["registered_pdd", "validation_report"],
    )


def check_monitoring_plan(facts) -> Finding | None:
    if not _missing(facts.get("monitoring_period_end")) or not _missing(facts.get("monitoring_plan_reference")):
        return None
    return _finding(
        "GEN_MON_001",
        "Medium",
        "No monitoring information found. A monitoring plan and period are required for verification.",
        "Need monitoring plan reference or completed monitoring period.",
        ["monitoring_report", "monitoring_plan"],
    )


def check_registration_or_listing(facts) -> Finding | None:
    if (
        not _missing(facts.get("registration_date"))
        or not _missing(facts.get("listing_date"))
        or not _missing(facts.get("approval_date"))
    ):
        return None
    return _finding(
        "GEN_REG_001",
        "Medium",
        "No registration or listing date found. Project approval date is required.",
        "Need a registration, listing, or approval date from the registry.",
        ["registration_record"],
    )


def run_all_checks(facts) -> list[Finding]:
    checks = [
        check_project_title,
        check_host_country,
        check_methodology_reference,
        check_validator_present,
        check_crediting_period,
        check_additionality_present,
        check_monitoring_plan,
        check_registration_or_listing,
    ]
    findings = [finding for check in checks if (finding := check(facts)) is not None]
    return sorted(findings, key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.flag_code))


def _finding(
    flag_code: str,
    severity: str,
    description: str,
    evidence_gap: str,
    required_documents: list[str],
) -> Finding:
    return Finding(
        finding_id=f"finding-{flag_code.lower().replace('_', '-')}",
        flag_code=flag_code,
        severity=severity,
        description=description,
        evidence_gap=evidence_gap,
        required_documents=required_documents,
        evidence_card_ids=[],
        review_status="open",
        reviewer_disposition="pending_human_review",
        reviewer_note="System-generated finding; not verified by a human reviewer.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
