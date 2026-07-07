import json

from core.ingestion import detect_document_type
from scripts.run_ingestion import ingest_paths, select_source_paths


def test_pdf_detection():
    assert detect_document_type("validation_report_9199.pdf") == "validation_report"
    assert detect_document_type("monitoring_report_9199.pdf") == "monitoring_report"
    assert detect_document_type("unknown.pdf") == "unknown"


def test_placeholder_fallback(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    placeholder = raw_dir / "validation_report_project_9199_placeholder.txt"
    placeholder.write_text(
        "## Validation Report for CDM Project 9199\n\n"
        "Document title: Validation Report\n"
        "Project ID: 9199\n"
        "Note: Placeholder pending manual download.\n",
        encoding="utf-8",
    )

    paths, using_real_pdfs = select_source_paths(raw_dir)
    assert not using_real_pdfs
    assert paths == [placeholder]

    ingest_paths(paths, processed_dir)
    parsed_path = processed_dir / "doc-9199-val_parsed_document.json"
    assert parsed_path.exists()
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    assert parsed["parse_status"] == "success"

