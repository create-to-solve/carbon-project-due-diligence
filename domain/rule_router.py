from __future__ import annotations

from core.models import Finding


def run_checks_for_project(facts: dict, methodology_type: str) -> list[Finding]:
    if methodology_type == "cdm_ar":
        from domain.rules_cdm import run_cdm_ar_checks

        return run_cdm_ar_checks(facts)
    from domain.rules_generic import run_all_checks

    return run_all_checks(facts)
