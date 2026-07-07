from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.audit import AuditLog
from core.models import CaseMemory


def build_case_snapshot(
    audit_log: AuditLog,
    project_id: str,
    subject_id: str,
    case_id: str,
    output_path: str,
) -> CaseMemory:
    timeline = [event.to_dict() for event in audit_log.read()]
    content_hash = hash_events(timeline)
    snapshot = CaseMemory(
        case_id=case_id,
        project_id=project_id,
        subject_id=subject_id,
        snapshot_timestamp=datetime.now(timezone.utc).isoformat(),
        event_count=len(timeline),
        content_hash=content_hash,
        timeline=timeline,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return snapshot


def hash_events(events: list[dict[str, Any]]) -> str:
    canonical = json.dumps(events, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_snapshot(snapshot: CaseMemory | dict[str, Any]) -> bool:
    payload = snapshot.to_dict() if isinstance(snapshot, CaseMemory) else snapshot
    return payload.get("content_hash") == hash_events(payload.get("timeline", []))


def subject_history(audit_log: AuditLog, subject_id: str) -> list[dict[str, Any]]:
    return [event.to_dict() for event in audit_log.get_subject_history(subject_id)]


def replay(snapshot_path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if not verify_snapshot(payload):
        raise ValueError("Case memory snapshot failed hash verification")
    return payload["timeline"]
