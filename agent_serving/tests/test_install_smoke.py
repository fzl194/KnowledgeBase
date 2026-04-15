"""Smoke test: verify package import works after pip install."""

import subprocess
import sys


def test_import_from_outside_repo(tmp_path):
    """Run import check from a temp directory to simulate installed package."""
    result = subprocess.run(
        [sys.executable, "-c", "from agent_serving.serving.main import app; print(app.title)"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    assert "Cloud Core Knowledge Backend" in result.stdout
