from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.audit import AuditLog  # noqa: E402
from core.evidence import load_evidence_cards  # noqa: E402
from core.memo import build_memo, memo_to_markdown, reviewer_questions_for  # noqa: E402
from core.paths import ProjectPaths  # noqa: E402
from core.project_manager import get_project  # noqa: E402
from domain.project_9199 import PROJECT_9199_FACTS  # noqa: E402
from domain.rules_cdm import run_all_checks  # noqa: E402

DEFAULT_PROJECT_ID = "project_9199"
_DEFAULT_PATHS = ProjectPaths(DEFAULT_PROJECT_ID, base_dir=ROOT)
CARDS_PATH = _DEFAULT_PATHS.evidence_cards_file
AUDIT_PATH = _DEFAULT_PATHS.audit_log
MEMO_PATH = _DEFAULT_PATHS.memo


def _confirmed_fact_count() -> int:
    path = _DEFAULT_PATHS.facts_file
    if not path.exists():
        return 0
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return len(records) if isinstance(records, list) else 0


def main() -> None:
    facts = dict(PROJECT_9199_FACTS)
    cards = load_evidence_cards(str(CARDS_PATH))
    findings = run_all_checks(facts)
    project_record = get_project(DEFAULT_PROJECT_ID, str(_DEFAULT_PATHS.project_registry))
    reviewer_questions = reviewer_questions_for(project_record, findings)
    confirmed_fact_count = _confirmed_fact_count()
    memo = build_memo(
        facts["project_id"],
        facts,
        cards,
        findings,
        AuditLog(str(AUDIT_PATH)),
        reviewer_questions=reviewer_questions,
        project_record=project_record,
        confirmed_fact_count=confirmed_fact_count,
    )
    MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMO_PATH.write_text(memo_to_markdown(memo), encoding="utf-8")
    print("Memo: data/outputs/memos/project_9199_memo.md")


if __name__ == "__main__":
    main()

