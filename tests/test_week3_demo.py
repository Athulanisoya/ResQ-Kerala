import json

import pytest
from pydantic import ValidationError

from backend.ai import rag_retriever
from backend.ai.rag_retriever import split_into_chunks, retrieve
from backend.schemas.shelter_schema import ShelterCreate


def test_shelter_rejects_occupancy_over_capacity():
    with pytest.raises(ValidationError):
        ShelterCreate(
            name="Demo Shelter",
            district="Alappuzha",
            locality="Alappuzha",
            address="Demo address",
            capacity=10,
            occupied=11,
        )


def test_full_shelter_is_not_marked_open():
    shelter = ShelterCreate(
        name="Demo Shelter",
        district="Alappuzha",
        locality="Alappuzha",
        address="Demo address",
        capacity=10,
        occupied=10,
    )

    assert shelter.status == "FULL"


def test_chunking_returns_text():
    chunks = split_into_chunks("word " * 250)

    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)


def test_rag_ignores_unapproved_documents(tmp_path, monkeypatch):
    file_path = tmp_path / "approved_safety_docs.json"
    file_path.write_text(
        json.dumps({
            "documents": [
                {
                    "title": "Approved Preparedness Document",
                    "source_name": "Demo approved authority",
                    "source_url": "https://example.org/preparedness",
                    "approved": True,
                    "text": (
                        "Flood preparedness guidance includes "
                        "an emergency plan and essential supplies."
                    ),
                },
                {
                    "title": "Unapproved Draft",
                    "source_name": "Draft",
                    "source_url": "",
                    "approved": False,
                    "text": (
                        "Flood guidance draft with emergency supplies."
                    ),
                },
            ]
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(rag_retriever, "DOCUMENT_PATH", file_path)
    rag_retriever.load_documents.cache_clear()
    rag_retriever.build_index.cache_clear()

    try:
        results = retrieve("flood preparedness guidance")

        assert results
        assert all(
            item["title"] == "Approved Preparedness Document"
            for item in results
        )
        assert all(item["approval_status"] == "unspecified" and item["review_required"] for item in results)
    finally:
        rag_retriever.load_documents.cache_clear()
        rag_retriever.build_index.cache_clear()

def test_shelter_without_source_does_not_claim_demo_provenance():
    shelter = ShelterCreate(
        name="Community Shelter", district="Kochi", locality="Kochi",
        address="Main Road", capacity=10,
    )
    assert shelter.source_name is None


def test_shelter_assistant_defaults_to_local_provider(monkeypatch):
    from backend.config import Settings
    monkeypatch.delenv("WEEK4_LLM_PROVIDER", raising=False)
    settings = Settings(_env_file=None, database_url="sqlite://",
                        allow_sqlite_for_tests=True, jwt_secret="x" * 32)
    assert settings.week4_llm_provider == "ollama"


def test_project_safety_references_disclose_review_status():
    from backend.ai import rag_retriever
    rag_retriever.load_documents.cache_clear()
    documents = rag_retriever.load_documents()
    assert documents
    assert any(item["approval_status"] == "official_source_paraphrase_for_project_review" for item in documents)
    assert all(item["review_required"] for item in documents)
