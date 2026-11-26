from backend.app.services.knowledge import chunk_text, retrieve
from backend.app.db import init_db
from backend.app.services.knowledge import ingest_directory


def test_chunk_text_keeps_short_paragraphs():
    chunks = chunk_text("First paragraph.\n\nSecond paragraph.")
    assert len(chunks) == 1
    assert "First paragraph" in chunks[0]


def test_local_retrieval_returns_relevant_source(tmp_path, test_knowledge_dir):
    db = tmp_path / "knowledge-test.db"
    init_db(db)
    count = ingest_directory(db, test_knowledge_dir)
    assert count >= 1
    results = retrieve(db, "Does the product confirm Shopify integration?", limit=3)
    assert results
    assert results[0]["source"] == "product.md"
    assert "Shopify" in results[0]["content"]
