"""Evaluation metrics and the offline evaluation run."""
from app.services.evaluation import classification_metrics, ranking_metrics


def test_classification_metrics():
    m = classification_metrics(["a", "a", "b", "b"], ["a", "b", "b", "b"])
    assert m["accuracy"] == 0.75
    assert m["per_class"]["a"]["precision"] == 1.0 and m["per_class"]["a"]["recall"] == 0.5
    assert 0 < m["f1_macro"] <= 1


def test_ranking_metrics():
    m = ranking_metrics([[0, 1, 0], [1, 0, 0], [0, 0, 0]], [1, 1, 1], k=3)
    assert m["recall_at_3"] == round(2 / 3, 4)
    assert m["mrr"] == round((0.5 + 1.0) / 3, 4)


def test_evaluation_run_on_held_out_split(client):
    response = client.post("/api/v1/analytics/evaluate", json={"split": "held_out_test", "limit": 6})
    assert response.status_code == 200, response.text
    metrics = response.json()["metrics"]
    assert metrics["leakage_check"]["evaluated_tickets_found_in_index"] == 0
    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro"):
        assert 0 <= metrics["classification"][key] <= 1
    assert "mrr" in metrics["retrieval"] and "ndcg_at_10" in metrics["retrieval"]
    assert set(metrics["rag"]) == {"groundedness", "citation_correctness", "citation_completeness", "answer_relevance"}
    assert metrics["unknown_detection"]["out_of_taxonomy_samples"] == 20
    runs = client.get("/api/v1/analytics/evaluations").json()["items"]
    assert runs and runs[0]["split"] == "held_out_test"


def test_invalid_split_rejected(client):
    assert client.post("/api/v1/analytics/evaluate", json={"split": "development"}).status_code == 422
