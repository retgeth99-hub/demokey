from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

SCORING_VERSION = "representative-v1"
BASE_WEIGHTS = {
    "relevance": 0.40,
    "citation": 0.20,
    "recency": 0.15,
    "publication_type": 0.15,
    "mesh_match": 0.10,
}

TYPE_WEIGHTS = {
    "meta-analysis": 1.0,
    "systematic review": 1.0,
    "randomized controlled trial": 0.95,
    "clinical trial": 0.85,
    "review": 0.75,
    "observational study": 0.7,
    "journal article": 0.55,
    "case reports": 0.35,
    "editorial": 0.2,
    "letter": 0.15,
}


@dataclass(frozen=True, slots=True)
class RankingInput:
    pmid: int
    pubmed_rank: int
    publication_date: date | None
    publication_types: tuple[str, ...]
    mesh_names: tuple[str, ...]
    major_mesh_names: tuple[str, ...]
    visible_citations: int | None


@dataclass(frozen=True, slots=True)
class RankingResult:
    pmid: int
    score: float
    components: dict[str, float | None]
    effective_weights: dict[str, float]
    missing_signals: tuple[str, ...]


def _percentiles(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    sorted_values = sorted(values.values())
    if len(sorted_values) == 1:
        return {key: 1.0 for key in values}
    result: dict[int, float] = {}
    for key, value in values.items():
        less_or_equal = sum(candidate <= value for candidate in sorted_values)
        result[key] = (less_or_equal - 1) / (len(sorted_values) - 1)
    return result


def rank_publications(
    items: Iterable[RankingInput],
    query_terms: set[str],
    today: date | None = None,
) -> list[RankingResult]:
    current = today or date.today()
    candidates = list(items)
    citation_values = {
        item.pmid: math.log1p(item.visible_citations)
        for item in candidates
        if item.visible_citations is not None
    }
    citation_percentiles = _percentiles(citation_values)
    output: list[RankingResult] = []
    max_rank = max((item.pubmed_rank for item in candidates), default=1)

    for item in candidates:
        relevance = 1.0 if max_rank == 1 else 1 - ((item.pubmed_rank - 1) / max_rank)
        if item.publication_date is None:
            recency = None
        else:
            age_days = max((current - item.publication_date).days, 0)
            recency = max(0.0, 1 - age_days / (365.25 * 5))
        publication_type = max(
            (TYPE_WEIGHTS.get(value.casefold(), 0.5) for value in item.publication_types),
            default=None,
        )
        mesh_tokens = {value.casefold() for value in item.mesh_names}
        major_tokens = {value.casefold() for value in item.major_mesh_names}
        if query_terms and mesh_tokens:
            matched = sum(2 if term in major_tokens else 1 for term in query_terms if term in mesh_tokens)
            mesh_match = min(matched / max(len(query_terms), 1), 1.0)
        else:
            mesh_match = None
        components: dict[str, float | None] = {
            "relevance": relevance,
            "citation": citation_percentiles.get(item.pmid),
            "recency": recency,
            "publication_type": publication_type,
            "mesh_match": mesh_match,
        }
        available = {key: weight for key, weight in BASE_WEIGHTS.items() if components[key] is not None}
        weight_sum = sum(available.values()) or 1.0
        effective = {key: weight / weight_sum for key, weight in available.items()}
        score = sum((components[key] or 0) * weight for key, weight in effective.items())
        missing = tuple(key for key, value in components.items() if value is None)
        output.append(RankingResult(item.pmid, score, components, effective, missing))

    return sorted(output, key=lambda value: (-value.score, value.pmid))

