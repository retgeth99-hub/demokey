from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisCreate(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    start_year: int | None = Field(default=None, ge=1800, le=3000)
    end_year: int | None = Field(default=None, ge=1800, le=3000)
    languages: list[str] = Field(default_factory=list, max_length=20)
    publication_types: list[str] = Field(default_factory=list, max_length=20)
    sort: Literal["relevance", "pub_date"] = "relevance"
    metadata_limit: int = Field(default=2000, ge=1, le=2000)
    abstract_limit: int = Field(default=500, ge=0, le=500)
    report_evidence_limit: int = Field(default=40, ge=1, le=50)
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_ranges(self) -> AnalysisCreate:
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year cannot be greater than end_year")
        if self.abstract_limit > self.metadata_limit:
            raise ValueError("abstract_limit cannot exceed metadata_limit")
        self.languages = sorted({value.strip() for value in self.languages if value.strip()})
        self.publication_types = sorted(
            {value.strip() for value in self.publication_types if value.strip()}
        )
        return self


class AnalysisAccepted(BaseModel):
    analysis_id: UUID
    status: str
    cache_hit: bool
    status_url: str


class AnalysisStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query_text: str
    normalized_query: str
    status: str
    phase: str | None
    progress_percent: float
    total_hit_count: int | None
    sampled_publication_count: int
    abstract_sample_count: int
    query_translation: str | None
    ai_status: str
    error_code: str | None
    error_detail: str | None
    retryable: bool
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisList(BaseModel):
    items: list[AnalysisStatus]
    page: int
    page_size: int
    total: int


class OverviewResponse(BaseModel):
    analysis_id: UUID
    query: str
    query_translation: str | None
    total_hit_count: int
    sampled_publication_count: int
    abstract_sample_count: int
    retrieved_at: datetime | None
    scoring_version: str
    region_method: str
    limitations: list[str]


class YearPoint(BaseModel):
    year: int | None
    count: int
    ratio: float


class YearTrendResponse(BaseModel):
    analysis_id: UUID
    sample_size: int
    items: list[YearPoint]


class RegionPoint(BaseModel):
    country_code: str | None
    country_name: str
    count: int
    ratio: float
    average_confidence: float | None
    is_unknown: bool


class RegionResponse(BaseModel):
    analysis_id: UUID
    method: str
    method_note: str
    items: list[RegionPoint]


class TermPoint(BaseModel):
    term: str
    document_count: int
    weighted_score: float
    sources: dict[str, object]


class TopicPoint(BaseModel):
    id: UUID
    index: int
    name: str
    summary: str
    publication_count: int
    share: float
    method: str
    confidence: float | None
    terms: list[str]
    representative_pmids: list[int]


class TopicsResponse(BaseModel):
    analysis_id: UUID
    terms: list[TermPoint]
    topics: list[TopicPoint]


class PublicationPoint(BaseModel):
    pmid: int
    title: str
    abstract: str | None
    journal: str | None
    publication_date: str | None
    doi: str | None
    rank: int | None
    score: float | None
    score_components: dict[str, object]
    scoring_version: str | None


class PublicationList(BaseModel):
    analysis_id: UUID
    items: list[PublicationPoint]
    page: int
    page_size: int
    total: int
    disclaimer: str


class ReportSectionResponse(BaseModel):
    key: str
    heading: str
    content: str
    evidence_pmids: list[int]
    evidence_status: str


class ReportResponse(BaseModel):
    analysis_id: UUID
    title: str
    body_markdown: str
    generation_mode: str
    ai_status: str
    model: str | None
    sections: list[ReportSectionResponse]
    limitations: list[str]
    disclaimer: str


class ActionResponse(BaseModel):
    analysis_id: UUID
    status: str


class HealthResponse(BaseModel):
    status: str
    database: str | None = None
    worker_enabled: bool | None = None

