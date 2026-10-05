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
    realistic = metrics["realistic"]
    assert realistic["questions"] == 63
    for key in ("intent_accuracy", "correct_article_first", "correct_article_in_top3", "clean_customer_wording",
                "answered_with_steps", "single_article_answers"):
        assert 0 <= realistic[key] <= 1
    assert all({"complaint", "expected_intent", "got_intent", "answered_from"} <= set(f) for f in realistic["failures"])
    # The small templated sample and demo-mode groundedness are flagged, not presented as plain 100% scores.
    assert any("distinct complaints" in w and "lower bound" in w for w in metrics["warnings"])
    assert any("Demo mode" in w for w in metrics["warnings"])
    # Each templated complaint is also tested in four realistic wordings.
    sample = metrics["sample"]
    assert sample["wordings"] == 5 and sample["tested"] == sample["unique_complaints"] * 5
    assert set(metrics["by_wording"]) == {"original", "short", "typos", "casual", "noise"}
    assert sum(w["total"] for w in metrics["by_wording"].values()) == sample["tested"]
    # Every rate carries its counts and a 95% lower bound below the measured value.
    accuracy = metrics["confidence"]["accuracy"]
    assert accuracy["total"] == sample["tested"] and accuracy["lower_95"] <= metrics["classification"]["accuracy"]
    assert metrics["generator"] == "template"
    runs = client.get("/api/v1/analytics/evaluations").json()["items"]
    assert runs and runs[0]["split"] == "held_out_test"


def test_invalid_split_rejected(client):
    assert client.post("/api/v1/analytics/evaluate", json={"split": "development"}).status_code == 422


def test_realistic_question_set_is_well_formed():
    import csv

    from app.config import ROOT_DIR
    intents = {r["name"] for r in csv.DictReader(open(ROOT_DIR / "data" / "intent_taxonomy.csv", encoding="utf-8"))}
    articles = {r["article_id"]: r for r in csv.DictReader(open(ROOT_DIR / "data" / "knowledge_base.csv", encoding="utf-8"))}
    rows = list(csv.DictReader(open(ROOT_DIR / "data" / "eval_realistic_complaints.csv", encoding="utf-8")))
    assert {r["expected_intent"] for r in rows} == intents  # every issue type is covered
    for row in rows:
        for article in row["expected_articles"].split("|"):
            assert articles[article]["intent"] == row["expected_intent"] and articles[article]["status"] == "ACTIVE"


def test_wording_check_flags_real_problems_only():
    from app.services.wording import customer_wording_issues
    assert customer_wording_issues("Located both charges.") == ["past-tense note"]
    assert customer_wording_issues("Route the case to billing support.") == ["agent jargon"]
    assert customer_wording_issues("Record the time pattern for.") == ["fragment"]
    assert customer_wording_issues("Check your current plan and choose the plan you'd like to move to.") == []


def test_wording_variants_are_realistic_and_repeatable():
    import random

    from app.services.evaluation import wording_variants
    text = "My broadband keeps disconnecting every evening. The issue has continued despite basic checks."
    first, again = wording_variants(text, random.Random(7)), wording_variants(text, random.Random(7))
    assert first == again  # seeded: every run tests the same messages
    assert first["short"] == "my broadband keeps disconnecting every evening"
    assert first["casual"].startswith("hey ") and first["casual"].endswith("can u help")
    assert first["typos"] != text and len(first["typos"]) == len(text)  # letters swapped, nothing added
    assert first["noise"].endswith(text) and len(first["noise"]) > len(text)


def test_perfect_scores_on_small_samples_have_a_lower_bound():
    from app.services.evaluation import wilson_lower
    assert wilson_lower(8, 8) == 0.6756          # 8/8 correct: the true rate is probably at least ~68%
    assert 0.9 < wilson_lower(40, 40) < 0.92     # more evidence, tighter bound
    assert wilson_lower(37, 40) < 37 / 40
    assert wilson_lower(0, 0) is None
