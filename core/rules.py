from __future__ import annotations

from core.models import Finding
from domain.rules_cdm import run_all_checks


def run_rule_checks(facts: dict) -> list[Finding]:
    return run_all_checks(facts)

