from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class AnalysisQuery:
    query: str
    start_year: int | None
    end_year: int | None
    languages: tuple[str, ...]
    publication_types: tuple[str, ...]
    sort: str
    metadata_limit: int
    abstract_limit: int
    report_evidence_limit: int
    algorithm_version: str = "2026-10-v1"


def normalize_query_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def build_pubmed_term(query: AnalysisQuery) -> str:
    parts = [normalize_query_text(query.query)]
    if query.start_year or query.end_year:
        start = query.start_year or 1800
        end = query.end_year or 3000
        parts.append(f'("{start}"[Date - Publication] : "{end}"[Date - Publication])')
    if query.languages:
        languages = " OR ".join(f'"{item}"[Language]' for item in sorted(query.languages))
        parts.append(f"({languages})")
    if query.publication_types:
        types = " OR ".join(f'"{item}"[Publication Type]' for item in sorted(query.publication_types))
        parts.append(f"({types})")
    return " AND ".join(parts)


def stable_query_payload(query: AnalysisQuery) -> dict[str, object]:
    payload = asdict(query)
    payload["query"] = normalize_query_text(query.query)
    payload["languages"] = sorted(query.languages)
    payload["publication_types"] = sorted(query.publication_types)
    return payload


def query_hash(query: AnalysisQuery) -> str:
    encoded = json.dumps(
        stable_query_payload(query), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

