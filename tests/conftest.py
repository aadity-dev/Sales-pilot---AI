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
def client(tmp_path: Path, test_knowledge_dir: Path):
    app = create_app(db_path=tmp_path / "salespilot-test.db", knowledge_dir=test_knowledge_dir)
    with TestClient(app) as test_client:
        yield test_client
