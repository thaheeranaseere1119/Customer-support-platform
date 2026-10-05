"""JSON wire format for the objects that cross service boundaries (gateway <-> nlu / retrieval / generation)."""
from __future__ import annotations

from dataclasses import asdict, fields

from app.services.classifier import Analysis
from app.services.rag import RAGAnswer
from app.services.retrieval import RetrievalFilters, RetrievalOutcome, ScoredSource


def _known(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def analysis_from(data: dict) -> Analysis:
    return Analysis(**_known(Analysis, data))


def source_to(src: ScoredSource) -> dict:
    return asdict(src)


def source_from(data: dict) -> ScoredSource:
    return ScoredSource(**_known(ScoredSource, data))


def filters_to(filters: RetrievalFilters | None) -> dict:
    filters = filters or RetrievalFilters()
    return {"guided_category": filters.guided_category, "exclude_source_ids": sorted(filters.exclude_source_ids),
            "source_types": sorted(filters.source_types) if filters.source_types is not None else None,
            "general_only": filters.general_only}


def filters_from(data: dict | None) -> RetrievalFilters:
    data = data or {}
    types = data.get("source_types")
    return RetrievalFilters(guided_category=data.get("guided_category"),
                            exclude_source_ids=set(data.get("exclude_source_ids") or []),
                            source_types=set(types) if types is not None else None,
                            general_only=bool(data.get("general_only")))


def outcome_to(outcome: RetrievalOutcome) -> dict:
    data = asdict(outcome)
    data["sources"] = [source_to(s) for s in outcome.sources]
    return data


def outcome_from(data: dict) -> RetrievalOutcome:
    values = _known(RetrievalOutcome, data)
    values["sources"] = [source_from(s) for s in data.get("sources", [])]
    return RetrievalOutcome(**values)


def answer_from(data: dict) -> RAGAnswer:
    return RAGAnswer(**_known(RAGAnswer, data))
