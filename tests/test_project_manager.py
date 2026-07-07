from __future__ import annotations

import json

import pytest

from core.paths import ProjectPaths
from core.project_manager import (
    create_project,
    get_project,
    load_project_registry,
    update_project_counts,
)


def _registry_path(tmp_path):
    base = tmp_path / "carbon-dd-v1"
    base.mkdir()
    (base / "data" / "projects").mkdir(parents=True)
    return base, base / "data" / "projects" / "registry.json"


def _create(tmp_path, project_id="project_test_001", methodology_type="generic"):
    base, registry_path = _registry_path(tmp_path)
    return base, registry_path, create_project(
        project_id=project_id,
        display_name=f"Test {project_id}",
        host_country="Testland",
        methodology="TEST-M v1",
        methodology_type=methodology_type,
        registry_path=str(registry_path),
        base_dir=base,
    )


def test_create_project_valid(tmp_path):
    base, registry_path, project = _create(tmp_path)
    assert project["project_id"] == "project_test_001"
    assert project["methodology_type"] == "generic"
    assert project["document_count"] == 0
    assert project["facts_count"] == 0
    assert project["findings_count"] == 0
    assert project["created_at"]

    registry = load_project_registry(str(registry_path))
    assert any(p["project_id"] == "project_test_001" for p in registry)

    paths = ProjectPaths("project_test_001", base_dir=base)
    assert paths.raw_documents.exists()
    assert paths.processed_documents.exists()
    assert paths.facts_file.exists()
    assert paths.evidence_cards_file.exists()
    assert json.loads(paths.facts_file.read_text(encoding="utf-8")) == []
    assert json.loads(paths.evidence_cards_file.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "bad_id",
    ["AB", "Project With Spaces", "PROJECT_UPPER", "project!", "ab"],
)
def test_create_project_invalid_id(tmp_path, bad_id):
    base, registry_path = _registry_path(tmp_path)
    with pytest.raises(ValueError):
        create_project(
            project_id=bad_id,
            display_name="x",
            host_country="x",
            methodology="x",
            methodology_type="generic",
            registry_path=str(registry_path),
            base_dir=base,
        )


def test_create_project_duplicate(tmp_path):
    base, registry_path, _ = _create(tmp_path)
    with pytest.raises(ValueError):
        create_project(
            project_id="project_test_001",
            display_name="dup",
            host_country="x",
            methodology="x",
            methodology_type="generic",
            registry_path=str(registry_path),
            base_dir=base,
        )


def test_get_project_found(tmp_path):
    _, registry_path, _ = _create(tmp_path)
    found = get_project("project_test_001", str(registry_path))
    assert found is not None
    assert found["project_id"] == "project_test_001"


def test_get_project_not_found(tmp_path):
    _, registry_path, _ = _create(tmp_path)
    assert get_project("project_does_not_exist", str(registry_path)) is None


def test_update_project_counts(tmp_path):
    _, registry_path, _ = _create(tmp_path)
    update_project_counts(
        "project_test_001",
        str(registry_path),
        document_count=4,
        findings_count=2,
    )
    project = get_project("project_test_001", str(registry_path))
    assert project["document_count"] == 4
    assert project["findings_count"] == 2
    assert project["facts_count"] == 0
