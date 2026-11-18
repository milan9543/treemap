from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Run each test in an empty directory with no $TREEMAP_CONFIG, so the repo's
    config.yaml is never picked up by accident."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TREEMAP_CONFIG", raising=False)
    return tmp_path


@pytest.fixture
def write_config(tmp_path):
    def _write(text: str, name: str = "config.yaml") -> Path:
        path = tmp_path / name
        path.write_text(text)
        return path

    return _write
