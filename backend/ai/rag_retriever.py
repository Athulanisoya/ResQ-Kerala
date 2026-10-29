import json
import re
from functools import lru_cache
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
DOCUMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "approved_safety_docs.json"
)

MIN_RELEVANCE = 0.08
CHUNK_WORDS = 180
CHUNK_OVERLAP = 35
def split_into_chunks(text: str) -> list[str]:
    words = re.findall(r"\S+", text)
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words):
            break
        start = end - CHUNK_OVERLAP

    return chunks
@lru_cache(maxsize=1)
def load_documents():
    if not DOCUMENT_PATH.exists():
        return []
    raw = json.loads(DOCUMENT_PATH.read_text(encoding="utf-8"))
    records = []
    for document in raw.get("documents", []):
        # Unapproved drafts must never be used as official evidence.
        if document.get("approved") is not True:
            continue
        title = str(document.get("title", "")).strip()
        source_url = str(document.get("source_url", "")).strip()
        source_name = str(document.get("source_name", "")).strip()
        text = str(document.get("text", "")).strip()
        if not title or not text:
            continue
        for number, chunk in enumerate(split_into_chunks(text), start=1):
            records.append({
                "title": title,
                "source_name": source_name or title,
                "source_url": source_url,
                "chunk_number": number,
                "text": chunk,
            })

    return records
@lru_cache(maxsize=1)
def build_index():
    documents = load_documents()
    if not documents:
        return documents, None, None
    vectorizer = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        strip_accents="unicode",
        sublinear_tf=True)
    matrix = vectorizer.fit_transform(item["text"] for item in documents)
    return documents, vectorizer, matrix
def retrieve(
    question: str,
    top_k: int = 4,
    min_relevance: float = MIN_RELEVANCE,
) -> list[dict]:
    question = (question or "").strip()
    if not question:
        return []
    documents, vectorizer, matrix = build_index()
    if not documents or vectorizer is None or matrix is None:
        return []
    question_vector = vectorizer.transform([question])
    scores = cosine_similarity(question_vector, matrix).ravel()
    ranked = scores.argsort()[::-1]
    results = []
    for index in ranked:
        score = float(scores[index])
        if score < min_relevance:
            break
        item = dict(documents[int(index)])
        item["relevance"] = round(score, 4)
        results.append(item)
        if len(results) >= max(1, min(top_k, 8)):
            break
    return results
def clear_retrieval_cache():
    """Call after approved_safety_docs.json is changed."""
    load_documents.cache_clear()
    build_index.cache_clear()