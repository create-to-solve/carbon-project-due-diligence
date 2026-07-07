import subprocess
import sys
from pathlib import Path

from core.memo import DISCLAIMER_TEXT

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "outputs" / "project_9199_review_pack.html"


def test_review_pack_generation_and_required_content():
    subprocess.run(
        [sys.executable, "scripts/build_review_pack.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert OUTPUT.exists()
    html = OUTPUT.read_text(encoding="utf-8")
    assert "AR_DEREG_001" in html
    assert "AR_ISS_GAP_001" in html
    assert DISCLAIMER_TEXT in html
    lowered = html.lower()
    assert "<html" in lowered
    assert "<head" in lowered
    assert "<body" in lowered

