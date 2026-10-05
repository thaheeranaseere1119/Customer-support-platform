"""In-process cache of the database-backed taxonomy (categories, intents, products)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntentTaxonomy, ProductCatalog, SupportCategory
from app.utils.text import tokenize


@dataclass(frozen=True)
class IntentInfo:
    name: str
    display_name: str
    description: str
    domain_category: str
    support_category: str
    default_product: str | None
    keywords: tuple[str, ...]
    examples: tuple[str, ...]
    clarifying_question: str | None
    origin: str


@dataclass
class TaxonomySnapshot:
    version: int = 0
    intents: dict[str, IntentInfo] = field(default_factory=dict)
    categories: dict[str, dict] = field(default_factory=dict)
    products: list[tuple[str, str, list[list[str]]]] = field(default_factory=list)  # name, category, keyword tokens

    def top_category(self, name: str | None) -> str:
        if not name:
            return "Unclassified"
        info = self.categories.get(name)
        if info and info.get("parent_name"):
            return info["parent_name"]
        return name if info else "Unclassified"

    def subcategory(self, name: str | None) -> str | None:
        info = self.categories.get(name or "")
        return name if info and info.get("parent_name") else None

    def categories_under(self, name: str) -> set[str]:
        matched = {name}
        matched |= {n for n, info in self.categories.items() if info.get("parent_name") == name}
        return matched

    @property
    def domain_categories(self) -> set[str]:
        return {i.domain_category for i in self.intents.values()}


class TaxonomyService:
    def __init__(self) -> None:
        self._snapshot = TaxonomySnapshot()
        self._dirty = True
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        self._dirty = True

    def get(self, db: Session) -> TaxonomySnapshot:
        if not self._dirty:
            return self._snapshot
        with self._lock:
            if not self._dirty:
                return self._snapshot
            snap = TaxonomySnapshot(version=self._snapshot.version + 1)
            for row in db.scalars(select(SupportCategory).order_by(SupportCategory.sort_order)):
                snap.categories[row.name] = {"parent_name": row.parent_name or None, "icon": row.icon,
                                             "description": row.description, "sort_order": row.sort_order}
            for row in db.scalars(select(IntentTaxonomy).where(IntentTaxonomy.status == "active")):
                snap.intents[row.name] = IntentInfo(
                    name=row.name, display_name=row.display_name, description=row.description,
                    domain_category=row.domain_category, support_category=row.support_category,
                    default_product=row.default_product, keywords=tuple(row.keywords or ()),
                    examples=tuple(row.example_complaints or ()), clarifying_question=row.clarifying_question,
                    origin=row.origin,
                )
            for row in db.scalars(select(ProductCatalog)):
                snap.products.append((row.name, row.support_category,
                                      [tokenize(k, keep_stopwords=True) for k in (row.keywords or [])]))
            self._snapshot = snap
            self._dirty = False
            return snap


taxonomy_service = TaxonomyService()
