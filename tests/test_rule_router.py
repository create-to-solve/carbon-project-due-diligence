from __future__ import annotations

from domain.project_9199 import PROJECT_9199_FACTS
from domain.rule_router import run_checks_for_project


def test_router_cdm_ar():
    findings = run_checks_for_project(dict(PROJECT_9199_FACTS), "cdm_ar")
    critical = [finding for finding in findings if finding.severity == "Critical"]
    flag_codes = {finding.flag_code for finding in critical}
    assert len(critical) == 2
    assert flag_codes == {"AR_DEREG_001", "AR_ISS_GAP_001"}


def test_router_generic():
    findings = run_checks_for_project({}, "generic")
    flag_codes = {finding.flag_code for finding in findings}
    assert "GEN_METH_001" in flag_codes
    assert "GEN_VAL_001" in flag_codes
    assert "GEN_ADD_001" in flag_codes


def test_router_unknown_type_falls_back_to_generic():
    findings = run_checks_for_project({}, "vcs")
    flag_codes = {finding.flag_code for finding in findings}
    assert "GEN_METH_001" in flag_codes
