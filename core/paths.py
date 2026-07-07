from __future__ import annotations

from pathlib import Path


class ProjectPaths:
    def __init__(self, project_id: str, base_dir: Path | None = None):
        self.project_id = project_id
        self.base = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent.parent
        self.data = self.base / "data"

    @property
    def raw_documents(self) -> Path:
        return self.data / "documents" / "raw" / self.project_id

    @property
    def processed_documents(self) -> Path:
        return self.data / "documents" / "processed" / self.project_id

    @property
    def facts_file(self) -> Path:
        return self.data / "facts" / f"{self.project_id}_facts.json"

    @property
    def proposals_file(self) -> Path:
        return self.data / "facts" / f"{self.project_id}_proposals.json"

    @property
    def evidence_cards_file(self) -> Path:
        return self.data / "evidence" / f"{self.project_id}_cards.json"

    @property
    def audit_log(self) -> Path:
        return self.data / "outputs" / "audit_logs" / f"{self.project_id}.jsonl"

    @property
    def memo(self) -> Path:
        return self.data / "outputs" / "memos" / f"{self.project_id}_memo.md"

    @property
    def narratives(self) -> Path:
        return self.data / "outputs" / "narratives" / f"{self.project_id}_narratives.json"

    @property
    def case_memory(self) -> Path:
        return self.data / "outputs" / "case_memory" / f"{self.project_id}_snapshot.json"

    @property
    def dispositions(self) -> Path:
        return self.data / "outputs" / "dispositions" / f"{self.project_id}_dispositions.json"

    @property
    def review_pack(self) -> Path:
        return self.data / "outputs" / f"{self.project_id}_review_pack.html"

    @property
    def pipeline_state(self) -> Path:
        return self.data / "outputs" / f"{self.project_id}_pipeline_state.json"

    @property
    def document_registry(self) -> Path:
        return self.data / "documents" / "registry.json"

    @property
    def project_registry(self) -> Path:
        return self.data / "projects" / "registry.json"
