from __future__ import annotations

import gzip
import hashlib
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.publications import ParsedPublication
from app.domain.query import AnalysisQuery, build_pubmed_term
from app.domain.ranking import SCORING_VERSION, RankingInput, rank_publications
from app.domain.regions import PARSER_VERSION as REGION_VERSION
from app.domain.regions import parse_country
from app.domain.reports import ReportPayload, template_report
from app.domain.topics import TERM_VERSION, TOPIC_VERSION, cluster_topics, extract_terms
from app.infrastructure.db.models import (
    Analysis,
    AnalysisJob,
    AnalysisPublication,
    AnalysisRegionStat,
    AnalysisReport,
    AnalysisReportEvidence,
    AnalysisReportSection,
    AnalysisStageRun,
    AnalysisTerm,
    AnalysisTopic,
    AnalysisTopicPublication,
    AnalysisTopicTerm,
    AnalysisYearStat,
    ContributorAffiliation,
    MeshTerm,
    Publication,
    PublicationCitationSnapshot,
    PublicationContributor,
    PublicationIdentifier,
    PublicationKeyword,
    PublicationMesh,
    PublicationType,
    PublicationTypeLink,
    PubmedQueryExecution,
    RawIngestBatch,
)
from app.infrastructure.deepseek.client import DeepSeekClient
from app.infrastructure.ncbi.client import NcbiClient, UpstreamError
from app.infrastructure.ncbi.parser import (
    PARSER_VERSION,
    parse_elink_cited_counts,
    parse_pubmed_xml,
)

logger = logging.getLogger(__name__)


class AnalysisCancelled(RuntimeError):
    pass


class AnalysisPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        ncbi_client: NcbiClient | None = None,
        deepseek_client: DeepSeekClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.ncbi = ncbi_client or NcbiClient(
            settings.ncbi_base_url,
            settings.ncbi_api_key,
            settings.ncbi_tool,
            settings.ncbi_email,
            settings.ncbi_rate_limit,
        )
        self.deepseek = deepseek_client or DeepSeekClient(
            settings.deepseek_base_url,
            settings.deepseek_api_key,
            settings.deepseek_model,
        )
        self._owns_clients = ncbi_client is None and deepseek_client is None

    async def close(self) -> None:
        if self._owns_clients:
            await self.ncbi.close()
            await self.deepseek.close()

    async def _analysis(self, session: AsyncSession, analysis_id: UUID) -> Analysis:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            raise RuntimeError(f"analysis {analysis_id} not found")
        return analysis

    async def _progress(self, analysis_id: UUID, phase: str, percent: float) -> None:
        async with self.session_factory() as session:
            analysis = await self._analysis(session, analysis_id)
            if analysis.status == "cancel_requested":
                raise AnalysisCancelled("analysis cancellation requested")
            analysis.phase = phase
            analysis.progress_percent = Decimal(str(max(float(analysis.progress_percent), percent)))
            job = await session.scalar(
                select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id)
            )
            if job is not None:
                now = datetime.now(UTC)
                attempt = max(job.attempt_count, 1)
                if job.current_stage and job.current_stage != phase:
                    previous = await session.scalar(
                        select(AnalysisStageRun).where(
                            AnalysisStageRun.analysis_id == analysis_id,
                            AnalysisStageRun.stage == job.current_stage,
                            AnalysisStageRun.attempt == attempt,
                            AnalysisStageRun.status == "running",
                        )
                    )
                    if previous is not None:
                        previous.status = "succeeded"
                        previous.finished_at = now
                current = await session.scalar(
                    select(AnalysisStageRun).where(
                        AnalysisStageRun.analysis_id == analysis_id,
                        AnalysisStageRun.stage == phase,
                        AnalysisStageRun.attempt == attempt,
                    )
                )
                if current is None:
                    session.add(
                        AnalysisStageRun(
                            analysis_id=analysis_id,
                            stage=phase,
                            attempt=attempt,
                            status="running",
                            input_summary={},
                            output_summary={"progress_percent": percent},
                            started_at=now,
                        )
                    )
                else:
                    current.output_summary = {"progress_percent": percent}
                job.current_stage = phase
                job.stage_checkpoint = {"phase": phase, "progress_percent": percent}
                job.heartbeat_at = now
                job.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
            await session.commit()

    async def _store_raw(
        self,
        session: AsyncSession,
        analysis_id: UUID,
        query_execution_id: UUID | None,
        source: str,
        batch_number: int,
        request_fingerprint: str,
        pmid_count: int,
        raw: bytes,
        status_code: int,
    ) -> None:
        compressed = gzip.compress(raw)
        session.add(
            RawIngestBatch(
                analysis_id=analysis_id,
                query_execution_id=query_execution_id,
                source=source,
                batch_number=batch_number,
                request_fingerprint=request_fingerprint,
                pmid_count=pmid_count,
                content_type="application/json" if source == "esearch" else "application/xml",
                content_encoding="gzip",
                payload=compressed,
                payload_sha256=hashlib.sha256(raw).hexdigest(),
                parser_version=PARSER_VERSION,
                http_status=status_code,
                retrieved_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=self.settings.raw_retention_days),
            )
        )

    async def _upsert_publications(
        self,
        session: AsyncSession,
        analysis_id: UUID,
        items: list[ParsedPublication],
        rank_by_pmid: dict[int, int],
        abstract_limit: int,
    ) -> dict[int, UUID]:
        pmids = [item.pmid for item in items]
        existing = {
            item.pmid: item
            for item in (
                await session.scalars(select(Publication).where(Publication.pmid.in_(pmids)))
            ).all()
        }
        now = datetime.now(UTC)
        publication_ids: dict[int, UUID] = {}
        abstract_cutoff = set(sorted(pmids, key=lambda pmid: rank_by_pmid[pmid])[:abstract_limit])

        for parsed in items:
            publication = existing.get(parsed.pmid)
            values: dict[str, Any] = {
                "title": parsed.title,
                "abstract_text": parsed.abstract_text,
                "abstract_sections": parsed.abstract_sections or None,
                "journal_title": parsed.journal_title,
                "journal_abbreviation": parsed.journal_abbreviation,
                "issn_print": parsed.issn_print,
                "issn_electronic": parsed.issn_electronic,
                "volume": parsed.volume,
                "issue": parsed.issue,
                "pagination": parsed.pagination,
                "language_codes": parsed.languages,
                "publication_date": parsed.publication_date,
                "publication_year": parsed.publication_year,
                "date_precision": parsed.date_precision,
                "is_retracted": parsed.is_retracted,
                "is_corrected": parsed.is_corrected,
                "data_quality_flags": parsed.quality_flags,
                "retrieved_at": now,
            }
            if publication is None:
                publication = Publication(pmid=parsed.pmid, **values)
                session.add(publication)
                await session.flush()
            else:
                for key, value in values.items():
                    setattr(publication, key, value)
                await session.flush()
                await session.execute(
                    delete(PublicationIdentifier).where(PublicationIdentifier.publication_id == publication.id)
                )
                await session.execute(
                    delete(PublicationContributor).where(PublicationContributor.publication_id == publication.id)
                )
                await session.execute(
                    delete(PublicationMesh).where(PublicationMesh.publication_id == publication.id)
                )
                await session.execute(
                    delete(PublicationKeyword).where(PublicationKeyword.publication_id == publication.id)
                )
                await session.execute(
                    delete(PublicationTypeLink).where(PublicationTypeLink.publication_id == publication.id)
                )

            publication_ids[parsed.pmid] = publication.id
            for kind, value in parsed.identifiers.items():
                normalized = value.casefold().strip()
                conflict = await session.scalar(
                    select(PublicationIdentifier).where(
                        PublicationIdentifier.identifier_type == kind,
                        PublicationIdentifier.normalized_value == normalized,
                    )
                )
                if conflict is None or conflict.publication_id == publication.id:
                    session.add(
                        PublicationIdentifier(
                            publication_id=publication.id,
                            identifier_type=kind,
                            identifier_value=value,
                            normalized_value=normalized,
                        )
                    )

            for contributor in parsed.contributors:
                contributor_row = PublicationContributor(
                    publication_id=publication.id,
                    position=contributor.position,
                    last_name=contributor.last_name,
                    fore_name=contributor.fore_name,
                    initials=contributor.initials,
                    collective_name=contributor.collective_name,
                    orcid=contributor.orcid,
                    is_first_author=contributor.position == 1,
                )
                session.add(contributor_row)
                await session.flush()
                for position, affiliation in enumerate(contributor.affiliations, start=1):
                    country = parse_country(affiliation.text)
                    session.add(
                        ContributorAffiliation(
                            contributor_id=contributor_row.id,
                            position=position,
                            affiliation_text=affiliation.text,
                            country_code=country.code,
                            country_name=country.name,
                            parse_confidence=Decimal(str(country.confidence)) if country.confidence else None,
                            parse_rule_id=country.rule_id,
                            parser_version=REGION_VERSION,
                        )
                    )

            for mesh in parsed.mesh_terms:
                mesh_row = await session.scalar(select(MeshTerm).where(MeshTerm.descriptor_ui == mesh.ui))
                if mesh_row is None:
                    mesh_row = MeshTerm(descriptor_ui=mesh.ui, descriptor_name=mesh.name)
                    session.add(mesh_row)
                    await session.flush()
                else:
                    mesh_row.descriptor_name = mesh.name
                session.add(
                    PublicationMesh(
                        publication_id=publication.id,
                        mesh_term_id=mesh_row.id,
                        is_major_topic=mesh.is_major,
                        qualifiers=mesh.qualifiers,
                    )
                )

            for keyword in parsed.keywords:
                session.add(
                    PublicationKeyword(
                        publication_id=publication.id,
                        keyword_text=keyword.text,
                        normalized_text=keyword.text.casefold().strip(),
                        is_major_topic=keyword.is_major,
                        source_owner=keyword.owner,
                    )
                )

            for pub_type in parsed.publication_types:
                type_row = await session.scalar(
                    select(PublicationType).where(PublicationType.type_ui == pub_type.ui)
                )
                if type_row is None:
                    type_row = PublicationType(type_ui=pub_type.ui, type_name=pub_type.name)
                    session.add(type_row)
                    await session.flush()
                else:
                    type_row.type_name = pub_type.name
                session.add(
                    PublicationTypeLink(
                        publication_id=publication.id, publication_type_id=type_row.id
                    )
                )

            association = await session.get(AnalysisPublication, (analysis_id, publication.id))
            if association is None:
                association = AnalysisPublication(
                    analysis_id=analysis_id,
                    publication_id=publication.id,
                    pubmed_rank=rank_by_pmid[parsed.pmid],
                    sample_order=rank_by_pmid[parsed.pmid],
                    has_abstract=bool(parsed.abstract_text),
                    is_abstract_sample=parsed.pmid in abstract_cutoff and bool(parsed.abstract_text),
                    created_at=now,
                )
                session.add(association)
            else:
                association.pubmed_rank = rank_by_pmid[parsed.pmid]
                association.sample_order = rank_by_pmid[parsed.pmid]
                association.has_abstract = bool(parsed.abstract_text)
                association.is_abstract_sample = parsed.pmid in abstract_cutoff and bool(parsed.abstract_text)
        return publication_ids

    async def _replace_aggregates(
        self,
        session: AsyncSession,
        analysis: Analysis,
        publications: list[ParsedPublication],
        publication_ids: dict[int, UUID],
        citation_counts: dict[int, int | None],
    ) -> list[int]:
        for model in (AnalysisYearStat, AnalysisRegionStat, AnalysisTopic, AnalysisTerm, AnalysisReport):
            await session.execute(delete(model).where(model.analysis_id == analysis.id))

        total = len(publications) or 1
        years = Counter(item.publication_year for item in publications)
        for year, count in sorted(years.items(), key=lambda pair: (pair[0] is None, pair[0] or 0)):
            session.add(
                AnalysisYearStat(
                    analysis_id=analysis.id,
                    year_key=str(year) if year else "unknown",
                    publication_year=year,
                    publication_count=count,
                    sample_ratio=Decimal(str(count / total)),
                    algorithm_version="year-v1",
                )
            )

        regions: Counter[tuple[str | None, str, bool]] = Counter()
        confidences: dict[tuple[str | None, str, bool], list[float]] = defaultdict(list)
        for item in publications:
            affiliation = None
            if item.contributors and item.contributors[0].affiliations:
                affiliation = item.contributors[0].affiliations[0].text
            match = parse_country(affiliation)
            key = (match.code, match.name or "未知", match.code is None)
            regions[key] += 1
            if match.confidence is not None:
                confidences[key].append(match.confidence)
        for (code, name, is_unknown), count in regions.most_common():
            values = confidences[(code, name, is_unknown)]
            session.add(
                AnalysisRegionStat(
                    analysis_id=analysis.id,
                    region_key=code or "unknown",
                    country_code=code,
                    country_name=name,
                    is_unknown=is_unknown,
                    publication_count=count,
                    sample_ratio=Decimal(str(count / total)),
                    average_confidence=Decimal(str(sum(values) / len(values))) if values else None,
                    method="first_author_affiliation",
                    algorithm_version=REGION_VERSION,
                )
            )

        weighted_terms = extract_terms(publications)
        term_rows: dict[str, AnalysisTerm] = {}
        for term_item in weighted_terms:
            row = AnalysisTerm(
                analysis_id=analysis.id,
                normalized_term=term_item.normalized,
                display_term=term_item.display,
                document_count=term_item.document_count,
                raw_frequency=term_item.raw_frequency,
                weighted_score=Decimal(str(term_item.weighted_score)),
                source_breakdown=term_item.sources,
                algorithm_version=TERM_VERSION,
            )
            session.add(row)
            term_rows[term_item.normalized] = row
        await session.flush()

        clusters = cluster_topics([item for item in publications if item.abstract_text][: analysis.abstract_limit])
        for index, cluster in enumerate(clusters, start=1):
            topic = AnalysisTopic(
                analysis_id=analysis.id,
                topic_index=index,
                name_zh=" / ".join(cluster.terms[:3]),
                summary_zh=f"该方向主要涉及：{'、'.join(cluster.terms[:6])}。",
                publication_count=len(cluster.pmids),
                share=Decimal(str(len(cluster.pmids) / total)),
                clustering_method=cluster.method,
                confidence=Decimal(str(cluster.confidence)) if cluster.confidence is not None else None,
                algorithm_parameters=cluster.parameters,
                algorithm_version=TOPIC_VERSION,
            )
            session.add(topic)
            await session.flush()
            for rank, term in enumerate(cluster.terms, start=1):
                term_row = term_rows.get(term)
                if term_row:
                    session.add(
                        AnalysisTopicTerm(
                            topic_id=topic.id,
                            analysis_term_id=term_row.id,
                            weight=Decimal(str(1 / rank)),
                            rank=rank,
                        )
                    )
            for rank, pmid in enumerate(cluster.pmids[:20], start=1):
                if pmid in publication_ids:
                    session.add(
                        AnalysisTopicPublication(
                            topic_id=topic.id,
                            publication_id=publication_ids[pmid],
                            membership_score=None,
                            is_representative=rank <= 5,
                            rank=rank,
                        )
                    )

        current = date.today()
        cutoff = current - timedelta(days=365 * 5)
        ranking_items = []
        by_pmid = {item.pmid: item for item in publications}
        for item in publications:
            if item.publication_date is None or item.publication_date < cutoff:
                continue
            ranking_items.append(
                RankingInput(
                    pmid=item.pmid,
                    pubmed_rank=next(
                        association.pubmed_rank or 1
                        for association in await session.scalars(
                            select(AnalysisPublication).where(
                                AnalysisPublication.analysis_id == analysis.id,
                                AnalysisPublication.publication_id == publication_ids[item.pmid],
                            )
                        )
                    ),
                    publication_date=item.publication_date,
                    publication_types=tuple(value.name for value in item.publication_types),
                    mesh_names=tuple(value.name for value in item.mesh_terms),
                    major_mesh_names=tuple(value.name for value in item.mesh_terms if value.is_major),
                    visible_citations=citation_counts.get(item.pmid),
                )
            )
        query_terms = {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", analysis.normalized_query)
            if token.casefold() not in {"and", "or", "not", "title", "abstract"}
        }
        ranked = rank_publications(ranking_items, query_terms, current)[:100]
        associations = {
            row.publication_id: row
            for row in (
                await session.scalars(
                    select(AnalysisPublication).where(AnalysisPublication.analysis_id == analysis.id)
                )
            ).all()
        }
        for association in associations.values():
            association.representative_rank = None
            association.representative_score = None
            association.score_components = {}
            association.scoring_version = None
            association.is_report_evidence = False
        for rank, result in enumerate(ranked, start=1):
            association = associations[publication_ids[result.pmid]]
            association.representative_rank = rank
            association.representative_score = Decimal(str(result.score))
            association.score_components = {
                "components": result.components,
                "effective_weights": result.effective_weights,
                "missing_signals": result.missing_signals,
            }
            association.scoring_version = SCORING_VERSION
        evidence = [
            result.pmid
            for result in ranked
            if by_pmid[result.pmid].abstract_text
        ][: analysis.report_evidence_limit]
        for pmid in evidence:
            associations[publication_ids[pmid]].is_report_evidence = True
        return evidence

    async def _persist_report(
        self,
        session: AsyncSession,
        analysis: Analysis,
        report: ReportPayload,
        generation_mode: str,
        provider: str,
        model: str | None,
        usage: dict[str, object],
        validation_status: str,
        publication_ids: dict[int, UUID],
    ) -> None:
        if report.topic_labels:
            topic_rows = (
                await session.scalars(
                    select(AnalysisTopic).where(AnalysisTopic.analysis_id == analysis.id)
                )
            ).all()
            topic_by_index = {topic.topic_index: topic for topic in topic_rows}
            for label in report.topic_labels:
                topic = topic_by_index.get(label.index)
                if topic is not None:
                    topic.name_zh = label.name_zh
                    topic.summary_zh = label.summary_zh
        existing = await session.scalar(
            select(AnalysisReport).where(AnalysisReport.analysis_id == analysis.id)
        )
        if existing:
            await session.delete(existing)
            await session.flush()
        body = "\n\n".join(f"## {item.heading}\n\n{item.content}" for item in report.sections)
        row = AnalysisReport(
            analysis_id=analysis.id,
            language="zh-CN",
            title=report.title,
            generation_mode=generation_mode,
            provider=provider,
            model_name=model,
            prompt_version="report-v1",
            schema_version="report-json-v1",
            body_markdown=body,
            character_count=sum(len(item.content) for item in report.sections),
            limitations=report.limitations,
            usage_metadata=usage,
            validation_status=validation_status,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        for position, section in enumerate(report.sections, start=1):
            section_row = AnalysisReportSection(
                report_id=row.id,
                section_key=section.key,
                position=position,
                heading=section.heading,
                content=section.content,
                evidence_pmids=section.evidence_pmids,
                evidence_status="supported" if section.evidence_pmids else "insufficient",
            )
            session.add(section_row)
            await session.flush()
            for order, pmid in enumerate(section.evidence_pmids, start=1):
                publication_id = publication_ids.get(pmid)
                if publication_id:
                    session.add(
                        AnalysisReportEvidence(
                            report_section_id=section_row.id,
                            publication_id=publication_id,
                            evidence_order=order,
                        )
                    )

    async def run(self, analysis_id: UUID) -> None:
        async with self.session_factory() as session:
            analysis = await self._analysis(session, analysis_id)
            params: dict[str, Any] = analysis.request_parameters
            query = AnalysisQuery(
                query=str(params["query"]),
                start_year=params.get("start_year"),
                end_year=params.get("end_year"),
                languages=tuple(params.get("languages", [])),
                publication_types=tuple(params.get("publication_types", [])),
                sort=str(params["sort"]),
                metadata_limit=int(params["metadata_limit"]),
                abstract_limit=int(params["abstract_limit"]),
                report_evidence_limit=int(params["report_evidence_limit"]),
                algorithm_version=str(params.get("algorithm_version", "2026-10-v1")),
            )

        await self._progress(analysis_id, "searching", 1)
        search = await self.ncbi.search(build_pubmed_term(query), query.metadata_limit, query.sort)
        async with self.session_factory() as session:
            analysis = await self._analysis(session, analysis_id)
            execution = PubmedQueryExecution(
                analysis_id=analysis_id,
                request_fingerprint=search.request_fingerprint,
                query_translation=search.query_translation,
                total_count=search.total_count,
                returned_id_count=len(search.ids),
                webenv_hash=hashlib.sha256(search.webenv.encode()).hexdigest() if search.webenv else None,
                query_key=search.query_key,
                http_status=200,
                duration_ms=search.duration_ms,
                executed_at=datetime.now(UTC),
            )
            session.add(execution)
            await session.flush()
            await self._store_raw(
                session,
                analysis_id,
                execution.id,
                "esearch",
                0,
                search.request_fingerprint,
                len(search.ids),
                search.raw,
                200,
            )
            analysis.total_hit_count = search.total_count
            analysis.query_translation = search.query_translation
            await session.commit()
            execution_id = execution.id

        if not search.ids:
            raise UpstreamError("PUBMED_NO_RESULTS", "PubMed returned no matching articles", retryable=False)

        rank_by_pmid = {pmid: index for index, pmid in enumerate(search.ids, start=1)}
        parsed_all: list[ParsedPublication] = []
        publication_ids: dict[int, UUID] = {}
        batches = [search.ids[index : index + 200] for index in range(0, len(search.ids), 200)]
        for batch_index, ids in enumerate(batches, start=1):
            await self._progress(
                analysis_id,
                "fetching_metadata",
                5 + 35 * ((batch_index - 1) / max(len(batches), 1)),
            )
            fetched = await self.ncbi.fetch(ids)
            parsed = parse_pubmed_xml(fetched.raw)
            parsed_all.extend(parsed)
            async with self.session_factory() as session:
                await self._store_raw(
                    session,
                    analysis_id,
                    execution_id,
                    "efetch",
                    batch_index,
                    fetched.request_fingerprint,
                    len(ids),
                    fetched.raw,
                    fetched.status_code,
                )
                publication_ids.update(
                    await self._upsert_publications(
                        session,
                        analysis_id,
                        parsed,
                        rank_by_pmid,
                        query.abstract_limit,
                    )
                )
                await session.commit()

        await self._progress(analysis_id, "enriching", 45)
        citation_counts: dict[int, int | None] = {}
        citation_candidates = search.ids[: min(500, len(search.ids))]
        for batch_index, start in enumerate(range(0, len(citation_candidates), 100), start=1):
            ids = citation_candidates[start : start + 100]
            try:
                linked = await self.ncbi.cited_by(ids)
                counts = parse_elink_cited_counts(linked.raw)
                citation_counts.update(counts)
                async with self.session_factory() as session:
                    await self._store_raw(
                        session,
                        analysis_id,
                        execution_id,
                        "elink",
                        batch_index,
                        linked.request_fingerprint,
                        len(ids),
                        linked.raw,
                        linked.status_code,
                    )
                    observed = datetime.now(UTC)
                    for pmid, count in counts.items():
                        publication_id = publication_ids.get(pmid)
                        if publication_id:
                            session.add(
                                PublicationCitationSnapshot(
                                    publication_id=publication_id,
                                    source="pubmed_citedin",
                                    visible_citation_count=count,
                                    coverage_note="PubMed 可见引用关系覆盖不完整。",
                                    observed_at=observed,
                                )
                            )
                    await session.commit()
            except UpstreamError:
                logger.warning("citation enrichment failed; continuing without citation signal", exc_info=True)

        await self._progress(analysis_id, "aggregating", 60)
        async with self.session_factory() as session:
            analysis = await self._analysis(session, analysis_id)
            analysis.sampled_publication_count = len(parsed_all)
            analysis.abstract_sample_count = min(
                sum(bool(item.abstract_text) for item in parsed_all), query.abstract_limit
            )
            evidence_pmids = await self._replace_aggregates(
                session, analysis, parsed_all, publication_ids, citation_counts
            )
            await session.commit()

        await self._progress(analysis_id, "generating_report", 86)
        year_counter = Counter(item.publication_year for item in parsed_all if item.publication_year)
        year_summary = "；".join(
            f"{year}年{count}篇" for year, count in sorted(year_counter.items())[-5:]
        )
        clusters = cluster_topics([item for item in parsed_all if item.abstract_text][: query.abstract_limit])
        topic_summary = "；".join("、".join(cluster.terms[:4]) for cluster in clusters[:5])
        by_pmid = {item.pmid: item for item in parsed_all}
        allowed_evidence_pmids = set(evidence_pmids)
        evidence_payload = {
            "query": analysis.normalized_query,
            "total_hits": search.total_count,
            "sample_count": len(parsed_all),
            "year_counts": dict(sorted(year_counter.items())),
            "topics": [
                {
                    "terms": cluster.terms,
                    "pmids": [
                        pmid for pmid in cluster.pmids if pmid in allowed_evidence_pmids
                    ][:10],
                }
                for cluster in clusters[:8]
            ],
            "publications": [
                {
                    "pmid": pmid,
                    "title": by_pmid[pmid].title,
                    "abstract": (by_pmid[pmid].abstract_text or "")[:2500],
                    "mesh": [term.name for term in by_pmid[pmid].mesh_terms],
                }
                for pmid in evidence_pmids
                if pmid in by_pmid
            ],
        }
        generation_mode = "deepseek"
        provider = "deepseek"
        model: str | None = self.settings.deepseek_model
        usage: dict[str, object] = {}
        validation_status = "valid"
        try:
            generated = await self.deepseek.generate_report(evidence_payload, set(evidence_pmids))
            report = generated.payload
            model = generated.model
            usage = generated.usage
            validation_status = generated.validation_status
            ai_status = "succeeded"
        except (UpstreamError, ValueError):
            logger.warning("DeepSeek report degraded to deterministic template", exc_info=True)
            report = template_report(
                analysis.normalized_query,
                search.total_count,
                len(parsed_all),
                year_summary,
                topic_summary,
                evidence_pmids,
            )
            generation_mode = "template_fallback"
            provider = "internal"
            model = None
            validation_status = "fallback"
            ai_status = "degraded"

        await self._progress(analysis_id, "finalizing", 97)
        async with self.session_factory() as session:
            analysis = await self._analysis(session, analysis_id)
            await self._persist_report(
                session,
                analysis,
                report,
                generation_mode,
                provider,
                model,
                usage,
                validation_status,
                publication_ids,
            )
            analysis.ai_status = ai_status
            analysis.phase = "completed"
            analysis.progress_percent = Decimal("100")
            analysis.status = "succeeded"
            analysis.completed_at = datetime.now(UTC)
            analysis.retryable = False
            running_stages = (
                await session.scalars(
                    select(AnalysisStageRun).where(
                        AnalysisStageRun.analysis_id == analysis_id,
                        AnalysisStageRun.status == "running",
                    )
                )
            ).all()
            for stage in running_stages:
                stage.status = "succeeded"
                stage.finished_at = analysis.completed_at
            await session.commit()

