PROJECT_9199_FACTS = {
    "project_id": "9199",
    "title": (
        "CDM Project for Forestry Restoration in Productive and Biological "
        "Corridors in the Eastern Plains of Colombia"
    ),
    "host_country": "Colombia",
    "sectoral_scope": "14 - Afforestation and reforestation",
    "methodology": "AR-AM0004 ver. 4",
    "baseline_methodology_ref": "AR-AM0004 ver. 4",
    "activity_scale": "Large",
    "validator_name": "DNV-CUK",
    "verifier_name": "AENOR",
    "registration_date": "2013-03-01",
    "deregistration_date": "2022-03-10",
    "crediting_period_start": "2005-06-02",
    "crediting_period_end": "2025-06-01",
    "annual_reductions_claimed_tco2e": 256109,
    "first_issuance_amount_cers": 908264,
    "second_issuance_amount_cers": 374589,
    "second_issuance_status": "awaiting_issuance_request",
    "host_party_approval": True,
    "host_party_approval_document": "Colombia Letter of Approval",
    "voluntary_cancellations_cers": 1257195,
    "cancellations_exceed_second_period_by_cers": 1257195 - 374589,
    "additionality_approach": "barrier_analysis",
    "permanence_risk_addressed": True,
    "monitoring_period_end": "2020-10-01",
    "source": "UNFCCC CDM Registry",
    "source_url": "https://cdm.unfccc.int/Projects/DB/DNV-CUK1356495554.91/view",
    "data_class": "structured_registry_data",
    "limitations": [
        "Derived from public UNFCCC CDM registry page.",
        "Not independently verified against primary documents.",
        (
            "Voluntary cancellation figure from analytical dataset, not "
            "confirmed against registry serial records."
        ),
    ],
}


def get_project_context() -> dict:
    return {
        "project_id": PROJECT_9199_FACTS["project_id"],
        "title": PROJECT_9199_FACTS["title"],
        "host_country": PROJECT_9199_FACTS["host_country"],
        "methodology": PROJECT_9199_FACTS["methodology"],
    }
