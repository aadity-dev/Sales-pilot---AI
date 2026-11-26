from __future__ import annotations

import math
import re
from pathlib import Path

from ..db import connect, new_id, utc_now

TOKEN_RE = re.compile(r"[a-zA-Z0-9₹]+", re.UNICODE)
STOP_WORDS = {
    "the", "a", "an", "is", "are", "do", "does", "did", "how", "what", "when",
    "where", "can", "could", "would", "will", "your", "you", "our", "we", "i",
    "me", "my", "to", "for", "of", "in", "on", "and", "or", "it", "this", "that",
    "about", "please", "tell", "want", "know", "with", "have", "has", "be", "available",
}


def _normalize_token(tok: str) -> str:
    if tok in {"secure", "security"}:
        return "secur"
    if tok in {"price", "prices", "pricing"}:
        return "pric"
    if tok.startswith("integrat"):
        return "integrat"
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokens(text: str) -> list[str]:
    return [
        _normalize_token(t.lower())
        for t in TOKEN_RE.findall(text)
        if len(t) > 1 and t.lower() not in STOP_WORDS
    ]


def chunk_text(text: str, max_chars: int = 700) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                if len(sentence) <= max_chars:
                    chunks.append(sentence.strip())
                else:
                    for start in range(0, len(sentence), max_chars):
                        chunks.append(sentence[start:start + max_chars].strip())
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def ingest_directory(db_path: str | Path, knowledge_dir: str | Path) -> int:
    directory = Path(knowledge_dir)
    documents: list[tuple[str, str]] = []
    if directory.exists():
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                for chunk in chunk_text(content):
                    documents.append((path.name, chunk))
    with connect(db_path) as conn:
        conn.execute("DELETE FROM knowledge_chunks")
        for source, content in documents:
            conn.execute(
                "INSERT INTO knowledge_chunks (id, source, content, created_at) VALUES (?, ?, ?, ?)",
                (new_id("chunk"), source, content, utc_now()),
            )
    return len(documents)


def retrieve(db_path: str | Path, query: str, limit: int = 3) -> list[dict[str, object]]:
    query_terms = tokens(query)
    if not query_terms:
        return []
    with connect(db_path) as conn:
        rows = conn.execute("SELECT id, source, content FROM knowledge_chunks").fetchall()
    if not rows:
        return []
    documents = [tokens(row["content"]) for row in rows]
    n_docs = len(documents)
    document_frequency: dict[str, int] = {}
    for doc in documents:
        for term in set(doc):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    query_counts: dict[str, int] = {}
    for term in query_terms:
        query_counts[term] = query_counts.get(term, 0) + 1

    ranked: list[tuple[float, dict[str, object]]] = []
    for row, doc_terms in zip(rows, documents):
        if not doc_terms:
            continue
        tf: dict[str, int] = {}
        for term in doc_terms:
            tf[term] = tf.get(term, 0) + 1
        score = 0.0
        for term, count in query_counts.items():
            if term in tf:
                idf = math.log(1 + (n_docs + 1) / (document_frequency.get(term, 0) + 1))
                score += (1 + math.log(count)) * (1 + math.log(tf[term])) * idf
        if score > 0:
            ranked.append((score, {
                "id": row["id"],
                "source": row["source"],
                "content": row["content"],
                "score": round(score, 4),
            }))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return []
    top_score = ranked[0][0]
    # Reject weak lexical matches rather than inventing an answer.
    return [item for score, item in ranked[:limit] if score >= max(1.0, top_score * 0.30)]
