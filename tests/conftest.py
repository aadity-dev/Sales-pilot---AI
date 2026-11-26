from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture()
def test_knowledge_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "knowledge"
    directory.mkdir()
    (directory / "product.md").write_text(
        "# Product FAQ\n\nThe fictional SalesPilot Demo supports customer support workflow automation.\n\n"
        "The sample documentation does not confirm a native Shopify integration. A product specialist must verify it.\n\n"
        "The sample Growth plan costs ₹50,000 per month.\n",
        encoding="utf-8",
    )
    return directory


@pytest.fixture()
def client(tmp_path: Path, test_knowledge_dir: Path, monkeypatch: pytest.MonkeyPatch):
    # Ensure tests stay isolated from any real .env keys on the developer's machine.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("SALESPILOT_LOCAL_LLM_URL", raising=False)
    app = create_app(
        db_path=tmp_path / "salespilot-test.db",
        knowledge_dir=test_knowledge_dir,
        env_path=tmp_path / ".env",
    )
    with TestClient(app) as test_client:
        yield test_client
