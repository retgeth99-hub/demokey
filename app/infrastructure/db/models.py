from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Analysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis"
    __table_args__ = (
        CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="progress_range"),
        CheckConstraint("metadata_limit > 0", name="metadata_limit_positive"),
        CheckConstraint("abstract_limit >= 0 AND abstract_limit <= metadata_limit", name="abstract_limit_valid"),
        CheckConstraint("report_evidence_limit BETWEEN 1 AND 50", name="evidence_limit_valid"),
        CheckConstraint("start_year IS NULL OR end_year IS NULL OR start_year <= end_year", name="year_range_valid"),
        Index(
            "ix_analysis_cache_lookup",
            "query_hash",
            "status",
            text("completed_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_analysis_history",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    start_year: Mapped[int | None] = mapped_column(SmallInteger)
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    sort_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="relevance")
    metadata_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    abstract_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    report_evidence_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    phase: Mapped[str | None] = mapped_column(String(64))
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    cache_source_analysis_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="SET NULL")
    )
    total_hit_count: Mapped[int | None] = mapped_column(BigInteger)
    sampled_publication_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstract_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    query_translation: Mapped[str | None] = mapped_column(Text)
    algorithm_versions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_job"
    __table_args__ = (
        Index(
            "ix_analysis_job_claim",
            "priority",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_analysis_job_expired_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(64))
    stage_checkpoint: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_detail: Mapped[str | None] = mapped_column(Text)


class AnalysisStageRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_stage_run"
    __table_args__ = (
        UniqueConstraint("analysis_id", "stage", "attempt", name="uq_stage_run_attempt"),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PubmedQueryExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pubmed_query_execution"

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    query_translation: Mapped[str | None] = mapped_column(Text)
    total_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    returned_id_count: Mapped[int] = mapped_column(Integer, nullable=False)
    webenv_hash: Mapped[str | None] = mapped_column(String(64))
    query_key: Mapped[str | None] = mapped_column(String(32))
    http_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RawIngestBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_ingest_batch"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "source",
            "batch_number",
            "request_fingerprint",
            name="uq_raw_ingest_batch_request",
        ),
        Index("ix_raw_ingest_batch_expires_at", "expires_at"),
    )

    analysis_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE")
    )
    query_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pubmed_query_execution.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    pmid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content_encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="gzip")
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publication"

    pmid: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract_text: Mapped[str | None] = mapped_column(Text)
    abstract_sections: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    journal_title: Mapped[str | None] = mapped_column(Text)
    journal_abbreviation: Mapped[str | None] = mapped_column(Text)
    issn_print: Mapped[str | None] = mapped_column(String(32))
    issn_electronic: Mapped[str | None] = mapped_column(String(32))
    volume: Mapped[str | None] = mapped_column(String(64))
    issue: Mapped[str | None] = mapped_column(String(64))
    pagination: Mapped[str | None] = mapped_column(String(128))
    language_codes: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, default=list)
    publication_date: Mapped[date | None] = mapped_column(Date)
    publication_year: Mapped[int | None] = mapped_column(SmallInteger, index=True)
    date_precision: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    is_retracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_revision: Mapped[str | None] = mapped_column(String(100))
    data_quality_flags: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationIdentifier(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_identifier"
    __table_args__ = (
        UniqueConstraint(
            "identifier_type", "normalized_value", name="uq_publication_identifier_value"
        ),
    )

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)


class PublicationContributor(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_contributor"
    __table_args__ = (
        UniqueConstraint("publication_id", "position", name="uq_publication_contributor_position"),
    )

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    last_name: Mapped[str | None] = mapped_column(Text)
    fore_name: Mapped[str | None] = mapped_column(Text)
    initials: Mapped[str | None] = mapped_column(String(32))
    collective_name: Mapped[str | None] = mapped_column(Text)
    orcid: Mapped[str | None] = mapped_column(String(64))
    is_first_author: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ContributorAffiliation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contributor_affiliation"
    __table_args__ = (
        UniqueConstraint(
            "contributor_id", "position", name="uq_contributor_affiliation_position"
        ),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
    )

    contributor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication_contributor.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    affiliation_text: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    country_name: Mapped[str | None] = mapped_column(Text)
    parse_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    parse_rule_id: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))


class MeshTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mesh_term"

    descriptor_ui: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    descriptor_name: Mapped[str] = mapped_column(Text, nullable=False)
    descriptor_type: Mapped[str | None] = mapped_column(String(64))


class PublicationMesh(Base):
    __tablename__ = "publication_mesh"

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), primary_key=True
    )
    mesh_term_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mesh_term.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    is_major_topic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qualifiers: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)


class PublicationKeyword(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_keyword"
    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "normalized_text",
            "source_owner",
            name="uq_publication_keyword_value",
        ),
    )

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_major_topic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_owner: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class PublicationType(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_type"

    type_ui: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    type_name: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_weight: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False, default=1)
    scoring_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")


class PublicationTypeLink(Base):
    __tablename__ = "publication_type_link"

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), primary_key=True
    )
    publication_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication_type.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PublicationCitationSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_citation_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "source", "observed_at", name="uq_citation_snapshot_observed"
        ),
    )

    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    visible_citation_count: Mapped[int | None] = mapped_column(Integer)
    coverage_note: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisPublication(Base):
    __tablename__ = "analysis_publication"
    __table_args__ = (
        CheckConstraint(
            "representative_score IS NULL OR (representative_score >= 0 AND representative_score <= 1)",
            name="representative_score_range",
        ),
        Index(
            "ix_analysis_publication_representative_rank",
            "analysis_id",
            "representative_rank",
            postgresql_where=text("representative_rank IS NOT NULL"),
        ),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), primary_key=True
    )
    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    pubmed_rank: Mapped[int | None] = mapped_column(Integer)
    sample_order: Mapped[int] = mapped_column(Integer, nullable=False)
    has_abstract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_abstract_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_report_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    representative_rank: Mapped[int | None] = mapped_column(Integer)
    representative_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    score_components: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    scoring_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisYearStat(Base):
    __tablename__ = "analysis_year_stat"

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), primary_key=True
    )
    year_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    publication_year: Mapped[int | None] = mapped_column(SmallInteger)
    publication_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisRegionStat(Base):
    __tablename__ = "analysis_region_stat"

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), primary_key=True
    )
    region_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    country_code: Mapped[str | None] = mapped_column(String(2))
    country_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False)
    publication_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    average_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisTerm(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_term"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "normalized_term", "algorithm_version", name="uq_analysis_term_version"
        ),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    normalized_term: Mapped[str] = mapped_column(Text, nullable=False)
    display_term: Mapped[str] = mapped_column(Text, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    weighted_score: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source_breakdown: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisTopic(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_topic"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "topic_index", "algorithm_version", name="uq_analysis_topic_version"
        ),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)
    publication_count: Mapped[int] = mapped_column(Integer, nullable=False)
    share: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    clustering_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    algorithm_parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisTopicTerm(Base):
    __tablename__ = "analysis_topic_term"

    topic_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_topic.id", ondelete="CASCADE"), primary_key=True
    )
    analysis_term_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_term.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class AnalysisTopicPublication(Base):
    __tablename__ = "analysis_topic_publication"

    topic_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_topic.id", ondelete="CASCADE"), primary_key=True
    )
    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="RESTRICT"), primary_key=True
    )
    membership_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    is_representative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int | None] = mapped_column(Integer)


class AnalysisReport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_report"

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    usage_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisReportSection(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_report_section"
    __table_args__ = (
        UniqueConstraint("report_id", "section_key", name="uq_report_section_key"),
        UniqueConstraint("report_id", "position", name="uq_report_section_position"),
    )

    report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_pmids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False, default=list)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisReportEvidence(Base):
    __tablename__ = "analysis_report_evidence"

    report_section_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_report_section.id", ondelete="CASCADE"), primary_key=True
    )
    publication_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publication.id", ondelete="RESTRICT"), primary_key=True
    )
    evidence_order: Mapped[int] = mapped_column(Integer, nullable=False)

