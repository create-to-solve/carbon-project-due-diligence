import json

from core.ingestion import citations_from_chunks, parse, read_registry, write_registry


def test_text_parser_produces_successful_document_and_chunks(tmp_path):
    path = tmp_path / "validation_report_project_9199.txt"
    path.write_text("## Heading\n\nFirst paragraph.\n\nSecond paragraph.", encoding="utf-8")
    document, chunks = parse(str(path))
    assert document.parse_status == "success"
    assert chunks
    assert chunks[0].chunk_id == "doc-9199-val-chunk-001"


def test_chunk_ids_are_unique_within_document(tmp_path):
    path = tmp_path / "monitoring_report_2016_2020_project_9199.txt"
    path.write_text("## Heading\n\nFirst.\n\nSecond.\n\nThird.", encoding="utf-8")
    _, chunks = parse(str(path))
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(ids) == len(set(ids))


def test_write_registry_preserves_cross_project_entries(tmp_path):
    registry_path = tmp_path / "carbon-dd-v1" / "data" / "documents" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    project_a_entry = {
        "document_id": "doc-a-001",
        "project_id": "project_a",
        "filename": "a.pdf",
        "document_type": "validation_report",
        "title": "Project A Validation",
        "source_path": "data/documents/raw/project_a/a.pdf",
        "ingested_at": "2026-06-28T00:00:00+00:00",
        "page_count": 12,
        "chunk_count": 9,
        "parse_status": "success",
        "parse_warnings": [],
    }
    registry_path.write_text(json.dumps([project_a_entry], indent=2), encoding="utf-8")

    project_b_record = {
        "document_id": "doc-b-001",
        "project_id": "project_b",
        "title": "Project B Methodology",
        "source_path": str(tmp_path / "b.pdf"),
        "document_type": "pdd",
        "ingested_at": "2026-06-29T00:00:00+00:00",
        "page_count": 30,
        "chunk_count": 21,
        "parse_status": "success",
        "parse_warnings": [],
    }
    write_registry([project_b_record], registry_path)

    merged = read_registry(registry_path)
    document_ids = {record["document_id"] for record in merged}
    assert document_ids == {"doc-a-001", "doc-b-001"}

    a_after = next(record for record in merged if record["document_id"] == "doc-a-001")
    assert a_after == project_a_entry


def test_write_registry_stores_project_id_without_double_prefix(tmp_path):
    registry_path = tmp_path / "carbon-dd-v1" / "data" / "documents" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    record = {
        "document_id": "doc-project0001-2cf0da1d",
        "project_id": "project0001",
        "title": "Validation Report Revision 1",
        "source_path": "data/documents/raw/project0001/Validation Report revision 1.pdf",
        "document_type": "validation_report",
        "ingested_at": "2026-06-29T00:00:00+00:00",
        "page_count": 16,
        "chunk_count": 16,
        "parse_status": "success",
        "parse_warnings": [],
    }
    write_registry([record], registry_path)
    merged = read_registry(registry_path)
    project_ids = {entry["project_id"] for entry in merged}
    assert project_ids == {"project0001"}
    assert "project_project0001" not in project_ids


def test_citations_reference_valid_chunks_and_excerpt_limit(tmp_path):
    path = tmp_path / "validation_report_project_9199.txt"
    path.write_text("## Heading\n\n" + "A" * 300, encoding="utf-8")
    document, chunks = parse(str(path))
    citations = citations_from_chunks(chunks, document)
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    assert {citation.chunk_id for citation in citations} <= chunk_ids
    assert all(len(citation.excerpt) <= 200 for citation in citations)

