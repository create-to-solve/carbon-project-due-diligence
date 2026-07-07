from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.paths import ProjectPaths

_PROJECT_ID_RE = re.compile(r"^[a-z0-9_]{3,50}$")


def load_project_registry(registry_path: str | Path) -> list[dict]:
    path = Path(registry_path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_project_registry(projects: list[dict], registry_path: str | Path) -> None:
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(projects, indent=2, sort_keys=True), encoding="utf-8")


def get_project(project_id: str, registry_path: str | Path) -> dict | None:
    for project in load_project_registry(registry_path):
        if project.get("project_id") == project_id:
            return project
    return None


def create_project(
    project_id: str,
    display_name: str,
    host_country: str,
    methodology: str,
    methodology_type: str,
    registry_path: str | Path,
    base_dir: Path | None = None,
) -> dict:
    if not _PROJECT_ID_RE.match(project_id or ""):
        raise ValueError(
            "project_id must be 3-50 characters, lowercase letters, "
            "numbers, and underscores only."
        )
    registry_path = Path(registry_path)
    projects = load_project_registry(registry_path)
    if any(project.get("project_id") == project_id for project in projects):
        raise ValueError(f"Project '{project_id}' already exists in the registry.")

    paths = ProjectPaths(project_id, base_dir=base_dir or registry_path.resolve().parents[2])
    for folder in (
        paths.raw_documents,
        paths.processed_documents,
        paths.facts_file.parent,
        paths.evidence_cards_file.parent,
        paths.audit_log.parent,
        paths.memo.parent,
        paths.narratives.parent,
        paths.case_memory.parent,
        paths.dispositions.parent,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    if not paths.facts_file.exists():
        paths.facts_file.write_text("[]", encoding="utf-8")
    if not paths.evidence_cards_file.exists():
        paths.evidence_cards_file.write_text("[]", encoding="utf-8")

    new_project = {
        "project_id": project_id,
        "display_name": display_name,
        "host_country": host_country,
        "methodology": methodology,
        "methodology_type": methodology_type,
        "status": "unknown",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "document_count": 0,
        "facts_count": 0,
        "findings_count": 0,
    }
    projects.append(new_project)
    save_project_registry(projects, registry_path)
    return new_project


def update_project_counts(
    project_id: str,
    registry_path: str | Path,
    document_count: int | None = None,
    facts_count: int | None = None,
    findings_count: int | None = None,
) -> None:
    projects = load_project_registry(registry_path)
    for project in projects:
        if project.get("project_id") != project_id:
            continue
        if document_count is not None:
            project["document_count"] = document_count
        if facts_count is not None:
            project["facts_count"] = facts_count
        if findings_count is not None:
            project["findings_count"] = findings_count
    save_project_registry(projects, registry_path)
