RISK_FLAGS = {
    "AR_ADD_001": {
        "severity": "High",
        "evidence_required": ["additionality_section", "investment_or_barrier_analysis"],
    },
    "AR_BASE_001": {
        "severity": "High",
        "evidence_required": ["registered_pdd", "methodology_reference"],
    },
    "AR_MON_001": {
        "severity": "Medium",
        "evidence_required": ["monitoring_report", "monitoring_period_dates"],
    },
    "AR_VAL_001": {
        "severity": "High",
        "evidence_required": ["validation_report", "validator_statement"],
    },
    "AR_REG_001": {
        "severity": "Medium",
        "evidence_required": ["registration_record"],
    },
    "AR_DEREG_001": {
        "severity": "Critical",
        "title": "Project deregistered",
        "description": (
            "Deregistered 10 March 2022. Credits issued under this project "
            "require verification of post-deregistration status."
        ),
        "evidence_required": ["deregistration_notice", "voluntary_cancellation_records"],
    },
    "AR_ISS_GAP_001": {
        "severity": "Critical",
        "title": "Second period credits unissued at deregistration",
        "description": (
            "374,589 CERs from monitoring period 2016-2020 remain at "
            "awaiting_issuance_request status at time of deregistration. "
            "Recovery pathway is uncertain."
        ),
        "evidence_required": [
            "second_monitoring_report",
            "verification_report_period_2",
            "deregistration_notice",
        ],
    },
    "AR_PERM_001": {
        "severity": "High",
        "evidence_required": ["permanence_risk_assessment", "buffer_or_reversal_treatment"],
    },
    "GEN_METH_001": {
        "severity": "High",
        "title": "No methodology reference found",
        "description": (
            "No approved methodology reference was identified. Carbon projects "
            "must apply and document an approved baseline methodology."
        ),
        "evidence_required": [
            "Project methodology document or PDD section referencing approved methodology",
        ],
    },
    "GEN_VAL_001": {
        "severity": "High",
        "title": "No validator identified",
        "description": (
            "No third-party validator (DOE) was identified in the project "
            "documents. Validation by an accredited body is required for "
            "credit issuance."
        ),
        "evidence_required": [
            "Validation report or registration certificate naming the validating DOE",
        ],
    },
    "GEN_ADD_001": {
        "severity": "High",
        "title": "Additionality not demonstrated",
        "description": (
            "No additionality approach was identified. All carbon projects "
            "must demonstrate that emission reductions would not have occurred "
            "without the carbon finance incentive."
        ),
        "evidence_required": [
            "PDD additionality section or validation report confirming additionality assessment",
        ],
    },
    "GEN_CRED_001": {
        "severity": "Medium",
        "title": "Crediting period not defined",
        "description": (
            "No crediting period start or end date was found. The crediting "
            "period defines the timeframe for which emission reductions can be claimed."
        ),
        "evidence_required": [
            "PDD or registration document confirming crediting period",
        ],
    },
    "GEN_MON_001": {
        "severity": "Medium",
        "title": "No monitoring information found",
        "description": (
            "No monitoring plan or monitoring period was identified. A "
            "monitoring plan is required for verification of emission reductions."
        ),
        "evidence_required": ["Monitoring plan from PDD or monitoring report"],
    },
    "GEN_REG_001": {
        "severity": "Medium",
        "title": "No registration or listing date",
        "description": (
            "No registration, listing, or approval date was found. Project "
            "registration date establishes the start of eligibility."
        ),
        "evidence_required": ["Registry listing or registration certificate"],
    },
    "GEN_TITLE_001": {
        "severity": "Low",
        "title": "Project title not found",
        "description": "No project title was identified in the documents.",
        "evidence_required": ["PDD cover page or registry entry"],
    },
    "GEN_COUNTRY_001": {
        "severity": "Low",
        "title": "Host country not identified",
        "description": "No host country was identified in the documents.",
        "evidence_required": ["PDD or registry entry confirming host country"],
    },
}


# Maps each finding flag to the AI-proposal claim_topic(s) that, once confirmed,
# would supply the evidence the finding is asking for. Used to tell a reviewer
# "an unconfirmed proposal may address this" — it never auto-resolves a finding.
FLAG_CLAIM_TOPICS: dict[str, list[str]] = {
    "AR_ADD_001": ["additionality", "additionality_demonstration"],
    "AR_BASE_001": ["baseline_methodology"],
    "AR_MON_001": ["monitoring", "monitoring_coverage_period_2"],
    "AR_VAL_001": ["validator", "project_identity"],
    "AR_REG_001": ["registration", "crediting_period"],
    "AR_DEREG_001": ["deregistration", "project_status"],
    "AR_ISS_GAP_001": ["issuance", "issuance_completeness", "monitoring_coverage_period_2"],
    "AR_PERM_001": ["permanence", "permanence_risk"],
    "GEN_METH_001": ["baseline_methodology"],
    "GEN_VAL_001": ["validator", "project_identity"],
    "GEN_ADD_001": ["additionality", "additionality_demonstration"],
    "GEN_MON_001": ["monitoring", "monitoring_coverage_period_2"],
    "GEN_CRED_001": ["crediting_period"],
    "GEN_REG_001": ["registration", "crediting_period"],
    "GEN_TITLE_001": ["project_identity"],
    "GEN_COUNTRY_001": ["project_identity"],
}


def claim_topics_for_flag(flag_code: str) -> list[str]:
    """Claim topics whose confirmed facts would address the given finding flag."""
    return FLAG_CLAIM_TOPICS.get(flag_code, [])


# Maps an expected-document identifier (as named in a finding's required_documents)
# to the held document_type(s) that satisfy "a document of this kind exists".
# Holding a document proves EXISTENCE only, never that its CONTENT resolves a
# finding — findings are driven by confirmed facts, not by document presence.
# Identifiers with no uploadable type (deregistration_notice,
# permanence_risk_assessment, registration_record, verification_report_period_2,
# voluntary_cancellation_records) are intentionally left unmapped so they remain
# genuine gaps.
EXPECTED_TO_HELD_TYPE: dict[str, list[str]] = {
    "registered_pdd": ["pdd"],
    "validation_report": ["validation_report"],
    "monitoring_report": ["monitoring_report"],
    "second_monitoring_report": ["monitoring_report"],
}


def expected_document_is_held(expected_id: str, held_types: set[str]) -> bool:
    """True when a held document_type satisfies the expected-document identifier.

    Existence only — this must never be used to close or downgrade a finding.
    """
    return any(held in held_types for held in EXPECTED_TO_HELD_TYPE.get(expected_id, []))
