"""The gateway calling separate nlu / retrieval / generation services gives the same results as one process.

Each service runs as its own FastAPI app (create_app(role)) behind a TestClient; the gateway talks to it over
HTTP through the same adapters that production uses.
"""
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import get_settings
from app.dependencies import get_container
from app.main import create_app
from app.services.adaptive_resolution import AdaptiveResolutionService
from app.services.embeddings import get_embedding_service
from app.services.remote import (
    RemoteClassifier,
    RemoteRAG,
    RemoteReranker,
    RemoteRetrieval,
    ServiceClient,
)
from app.services.retrieval import RetrievalFilters, RetrievalService
from app.services.taxonomy import taxonomy_service

TOKEN = "internal-test-token-0123456789"
COMPLAINT = ("My broadband drops every evening around 8 and I've already restarted the router twice, "
             "I work from home and this is costing me")


@pytest.fixture(scope="module")
def services(client):
    settings = get_settings()
    original = settings.internal_api_token
    object.__setattr__(settings, "internal_api_token", SecretStr(TOKEN))
    local = get_container().services  # the services keep their own in-process implementations
    apps = {role: TestClient(create_app(role, services=lambda: local)) for role in ("nlu", "retrieval", "generation")}
    for app_client in apps.values():
        app_client.__enter__()
    yield apps
    for app_client in apps.values():
        app_client.__exit__(None, None, None)
    object.__setattr__(settings, "internal_api_token", original)


def remote(services, role) -> ServiceClient:
    return ServiceClient(role, "http://testserver", client=services[role])


@pytest.fixture()
def split_gateway(services):
    """Give the running gateway a pipeline whose nlu / retrieval / generation steps go over HTTP."""
    container = get_container()
    local = container.services
    retrieval_client = remote(services, "retrieval")
    split = dataclasses.replace(
        local, classifier=RemoteClassifier(remote(services, "nlu"), local.embeddings, local.classifier.llm),
        retrieval=RemoteRetrieval(retrieval_client, local.embeddings), reranker=RemoteReranker(retrieval_client),
        rag=RemoteRAG(remote(services, "generation")))
    saved = (container.services, container.pipeline)
    container.services, container.pipeline = split, AdaptiveResolutionService(split)
    yield split
    container.services, container.pipeline = saved


@pytest.mark.parametrize("role,path", [("nlu", "/internal/v1/classify"), ("retrieval", "/internal/v1/search"),
                                       ("generation", "/internal/v1/generate")])
def test_internal_endpoints_need_the_internal_token(services, role, path):
    app_client = services[role]
    assert app_client.post(path, json={}).status_code == 403
    assert app_client.post(path, json={}, headers={"X-Internal-Token": "wrong"}).status_code == 403
    assert app_client.get("/internal/v1/health", headers={"X-Internal-Token": TOKEN}).json()["role"] == role
    assert app_client.get("/api/v1/health").status_code == 404  # services expose only their own internal API


def test_remote_classification_matches_in_process(services, db):
    local = get_container().services.classifier.classify(db, COMPLAINT)
    remote_result = RemoteClassifier(remote(services, "nlu"), get_embedding_service(), None).classify(db, COMPLAINT)
    assert remote_result.to_dict() == local.to_dict()
    assert (remote_result.intent, remote_result.product, remote_result.severity, remote_result.sentiment) == (
        "broadband_disconnects", "broadband", "high", "frustrated")


def test_remote_search_and_rerank_match_in_process(services, db):
    s = get_container().services
    taxonomy = taxonomy_service.get(db)
    vector = s.embeddings.embed_one(COMPLAINT)
    args = {"intent": "broadband_disconnects", "category": "Internet", "product": "broadband", "taxonomy": taxonomy,
            "filters": RetrievalFilters(exclude_source_ids={"KB-999"}), "top_k": 10, "query_vector": vector}
    local = s.retrieval.search(db, COMPLAINT, **args)
    client = remote(services, "retrieval")
    over_http = RemoteRetrieval(client, s.embeddings).search(db, COMPLAINT, **args)
    assert [x.source_id for x in over_http.sources] == [x.source_id for x in local.sources]
    local_ranked, local_method = s.reranker.rerank(COMPLAINT, local.sources)
    ranked, method = RemoteReranker(client).rerank(COMPLAINT, over_http.sources)
    assert method == local_method and [x.source_id for x in ranked] == [x.source_id for x in local_ranked]


def test_full_resolution_through_the_split_services(client, split_gateway, session_id):
    response = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": COMPLAINT})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["analysis"]["intent"] == "broadband_disconnects"
    assert data["case_status"] == "awaiting_feedback" and data["resolution"]["steps"]
    sources = {s["source_id"] for s in data["retrieval"]["sources"]}
    assert all(step["citations"] and set(step["citations"]) <= sources for step in data["resolution"]["steps"])
    assert any(step.get("already_attempted") for step in data["resolution"]["steps"])  # "already restarted the router"
    health = client.get("/api/v1/health").json()
    assert health["services"] == {"nlu": "ok", "retrieval": "ok", "generation": "ok"}


def test_generation_outage_falls_back_to_the_cited_template(client, split_gateway, session_id):
    split_gateway.rag = RemoteRAG(ServiceClient("generation", "http://127.0.0.1:9",
                                                client=httpx.Client(base_url="http://127.0.0.1:9", timeout=1)))
    data = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": COMPLAINT}).json()
    assert data["resolution"]["generator"] == "grounded_template_fallback"
    assert data["resolution"]["steps"] and all(step["citations"] for step in data["resolution"]["steps"])
    assert any("answer service was unavailable" in w for w in data["resolution"]["warnings"])


def test_retrieval_outage_is_reported_not_guessed(client, split_gateway, session_id):
    split_gateway.retrieval = RemoteRetrieval(ServiceClient("retrieval", "http://127.0.0.1:9",
                                                            client=httpx.Client(base_url="http://127.0.0.1:9", timeout=1)),
                                              split_gateway.embeddings)
    response = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": COMPLAINT})
    assert response.status_code == 502 and response.json()["error"]["code"] == "RETRIEVAL_FAILED"


def test_a_separate_search_index_sees_new_articles_without_being_told(client, db):
    other_process = RetrievalService(get_embedding_service())  # e.g. the retrieval service or another worker
    taxonomy = taxonomy_service.get(db)

    def found() -> bool:
        outcome = other_process.search(db, "quantum entanglement router pairing", intent=None, category=None,
                                       product=None, taxonomy=taxonomy, top_k=5)
        return any("Quantum pairing" in x.title for x in outcome.sources)

    assert not found()
    created = client.post("/api/v1/knowledge", json={
        "title": "Quantum pairing of the router", "category": "Wi-Fi", "intent": "wifi_not_working", "status": "ACTIVE",
        "content": "Symptoms: Quantum entanglement router pairing fails.\nResolution steps:\n1. Re-pair the router."})
    assert created.status_code == 201
    db.expire_all()
    assert found()  # rebuilt because the chunk fingerprint changed, with no in-process notification
