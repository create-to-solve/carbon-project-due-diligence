from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import ProjectPaths  # noqa: E402

PROJECT_ID = "project_9199"
_DEFAULT_PATHS = ProjectPaths(PROJECT_ID, base_dir=ROOT)
DATA_DIR = _DEFAULT_PATHS.data
PROCESSED_DIR = _DEFAULT_PATHS.processed_documents
FACTS_PATH = _DEFAULT_PATHS.facts_file


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chunks = _load_chunks()
    citations_by_chunk = _load_citations_by_chunk()
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))

    for fact in facts:
        old_citations = list(fact.get("citation_ids", []))
        match = _find_match(fact, chunks, citations_by_chunk)
        print(f"Fact: {fact.get('label')}")
        print(f"Old citation: {', '.join(old_citations) if old_citations else 'none'}")
        if match is None:
            print("No match found — keeping existing citation")
            continue
        chunk, citation_id, matched_terms = match
        fact["citation_ids"] = [citation_id]
        fact["matched_terms"] = matched_terms
        print(
            "New citation: "
            f"{citation_id} (matched in chunk {chunk.get('chunk_id')}, page {chunk.get('page_number')})"
        )
        print(f"Matched terms: {', '.join(matched_terms)}")

    FACTS_PATH.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")


def _load_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(PROCESSED_DIR.glob("*_chunks.json")):
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    return chunks


def _load_citations_by_chunk() -> dict[str, str]:
    citations_by_chunk: dict[str, str] = {}
    for path in sorted(PROCESSED_DIR.glob("*_citations.json")):
        for citation in json.loads(path.read_text(encoding="utf-8")):
            citations_by_chunk[citation["chunk_id"]] = citation["citation_id"]
    return citations_by_chunk


def _find_match(
    fact: dict[str, Any],
    chunks: list[dict[str, Any]],
    citations_by_chunk: dict[str, str],
) -> tuple[dict[str, Any], str, list[str]] | None:
    terms = _search_terms(fact)
    best_match: tuple[dict[str, Any], str, list[str]] | None = None
    best_count = 0
    for chunk in chunks:
        text = str(chunk.get("text", "")).lower()
        matched_terms = [term for term in terms if term.lower() in text]
        citation_id = citations_by_chunk.get(chunk["chunk_id"])
        if citation_id and len(matched_terms) > best_count:
            best_match = (chunk, citation_id, matched_terms)
            best_count = len(matched_terms)
    return best_match


def _search_terms(fact: dict[str, Any]) -> list[str]:
    values = fact.get("search_terms") or [fact.get("label")]
    terms = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip().lower()
        if text:
            terms.append(text)
    return terms


if __name__ == "__main__":
    main()
