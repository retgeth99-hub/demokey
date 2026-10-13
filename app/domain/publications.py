from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class ParsedAffiliation:
    text: str


@dataclass(slots=True)
class ParsedContributor:
    position: int
    last_name: str | None = None
    fore_name: str | None = None
    initials: str | None = None
    collective_name: str | None = None
    orcid: str | None = None
    affiliations: list[ParsedAffiliation] = field(default_factory=list)


@dataclass(slots=True)
class ParsedMesh:
    ui: str
    name: str
    is_major: bool = False
    qualifiers: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedKeyword:
    text: str
    is_major: bool = False
    owner: str = ""


@dataclass(slots=True)
class ParsedPublicationType:
    ui: str
    name: str


@dataclass(slots=True)
class ParsedPublication:
    pmid: int
    title: str
    abstract_text: str | None
    abstract_sections: list[dict[str, str]]
    journal_title: str | None
    journal_abbreviation: str | None
    issn_print: str | None
    issn_electronic: str | None
    volume: str | None
    issue: str | None
    pagination: str | None
    languages: list[str]
    publication_date: date | None
    publication_year: int | None
    date_precision: str
    identifiers: dict[str, str]
    contributors: list[ParsedContributor]
    mesh_terms: list[ParsedMesh]
    keywords: list[ParsedKeyword]
    publication_types: list[ParsedPublicationType]
    is_retracted: bool = False
    is_corrected: bool = False
    quality_flags: dict[str, object] = field(default_factory=dict)

