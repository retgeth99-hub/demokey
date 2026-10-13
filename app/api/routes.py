from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ActionResponse,
    AnalysisAccepted,
    AnalysisCreate,
    AnalysisList,
    AnalysisStatus,
    HealthResponse,
    OverviewResponse,
    PublicationList,
    PublicationPoint,
    RegionPoint,
    RegionResponse,
    ReportResponse,
    ReportSectionResponse,
    TermPoint,
    TopicPoint,
    TopicsResponse,
    YearPoint,
    YearTrendResponse,
)
from app.application.analyses import AnalysisService
from app.core.config import Settings, get_settings
from app.core.security import require_service_key
from app.infrastructure.db.models import (
    AnalysisPublication,
    AnalysisRegionStat,
    AnalysisReport,
    AnalysisReportSection,
    AnalysisTerm,
    AnalysisTopic,
    AnalysisTopicPublication,
    AnalysisTopicTerm,
    AnalysisYearStat,
    Publication,
    PublicationIdentifier,
)
from app.infrastructure.db.session import get_session

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_service_key)])
health_router = APIRouter(prefix="/health")


def _service(
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)
) -> AnalysisService:
    return AnalysisService(session, settings)


def _status(analysis: object) -> AnalysisStatus:
    return AnalysisStatus.model_validate(analysis)


@router.post(
    "/analyses",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": AnalysisAccepted}},
)
async def create_analysis(payload: AnalysisCreate, response: Response, service: AnalysisService = Depends(_service)) -> AnalysisAccepted:
    analysis, cache_hit = await service.create(payload)
    if cache_hit:
        response.status_code = status.HTTP_200_OK
    return AnalysisAccepted(
        analysis_id=analysis.id,
        status=analysis.status,
        cache_hit=cache_hit,
        status_url=f"/api/v1/analyses/{analysis.id}",
    )


@router.get("/analyses", response_model=AnalysisList)
async def list_analyses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: AnalysisService = Depends(_service),
) -> AnalysisList:
    items, total = await service.list(page, page_size)
    return AnalysisList(items=[_status(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/analyses/{analysis_id}", response_model=AnalysisStatus)
async def get_analysis(analysis_id: UUID, service: AnalysisService = Depends(_service)) -> AnalysisStatus:
    return _status(await service.get(analysis_id))


@router.post("/analyses/{analysis_id}/cancel", response_model=ActionResponse)
async def cancel_analysis(analysis_id: UUID, service: AnalysisService = Depends(_service)) -> ActionResponse:
    analysis = await service.cancel(analysis_id)
    return ActionResponse(analysis_id=analysis.id, status=analysis.status)


@router.post("/analyses/{analysis_id}/retry", response_model=ActionResponse)
async def retry_analysis(analysis_id: UUID, service: AnalysisService = Depends(_service)) -> ActionResponse:
    analysis = await service.retry(analysis_id)
    return ActionResponse(analysis_id=analysis.id, status=analysis.status)


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: UUID, service: AnalysisService = Depends(_service)) -> Response:
    await service.soft_delete(analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/analyses/{analysis_id}/overview", response_model=OverviewResponse)
async def get_overview(
    analysis_id: UUID,
    service: AnalysisService = Depends(_service),
) -> OverviewResponse:
    analysis = await service.ensure_ready(analysis_id)
    return OverviewResponse(
        analysis_id=analysis.id,
        query=analysis.normalized_query,
        query_translation=analysis.query_translation,
        total_hit_count=analysis.total_hit_count or 0,
        sampled_publication_count=analysis.sampled_publication_count,
        abstract_sample_count=analysis.abstract_sample_count,
        retrieved_at=analysis.completed_at,
        scoring_version=str(analysis.algorithm_versions.get("ranking", "representative-v1")),
        region_method="first_author_affiliation",
        limitations=[
            "总命中量来自 PubMed，统计仅基于实际分析样本。",
            "国家/地区根据第一作者单位文本推断，不代表研究发生地。",
            "PubMed 可见引用关系覆盖不完整。",
        ],
    )


@router.get("/analyses/{analysis_id}/trends", response_model=YearTrendResponse)
async def get_trends(
    analysis_id: UUID,
    service: AnalysisService = Depends(_service),
) -> YearTrendResponse:
    analysis = await service.ensure_ready(analysis_id)
    rows = (
        await service.session.scalars(
            select(AnalysisYearStat)
            .where(AnalysisYearStat.analysis_id == analysis_id)
            .order_by(AnalysisYearStat.publication_year.asc().nulls_last())
        )
    ).all()
    return YearTrendResponse(
        analysis_id=analysis_id,
        sample_size=analysis.sampled_publication_count,
        items=[
            YearPoint(year=row.publication_year, count=row.publication_count, ratio=float(row.sample_ratio))
            for row in rows
        ],
    )


@router.get("/analyses/{analysis_id}/regions", response_model=RegionResponse)
async def get_regions(
    analysis_id: UUID,
    service: AnalysisService = Depends(_service),
) -> RegionResponse:
    await service.ensure_ready(analysis_id)
    rows = (
        await service.session.scalars(
            select(AnalysisRegionStat)
            .where(AnalysisRegionStat.analysis_id == analysis_id)
            .order_by(AnalysisRegionStat.publication_count.desc(), AnalysisRegionStat.country_name)
        )
    ).all()
    return RegionResponse(
        analysis_id=analysis_id,
        method="first_author_affiliation",
        method_note="根据第一作者首个单位的自由文本推断，无法判断的记录归入未知。",
        items=[
            RegionPoint(
                country_code=row.country_code,
                country_name=row.country_name,
                count=row.publication_count,
                ratio=float(row.sample_ratio),
                average_confidence=float(row.average_confidence) if row.average_confidence is not None else None,
                is_unknown=row.is_unknown,
            )
            for row in rows
        ],
    )


@router.get("/analyses/{analysis_id}/topics", response_model=TopicsResponse)
async def get_topics(
    analysis_id: UUID,
    service: AnalysisService = Depends(_service),
) -> TopicsResponse:
    await service.ensure_ready(analysis_id)
    terms = (
        await service.session.scalars(
            select(AnalysisTerm)
            .where(AnalysisTerm.analysis_id == analysis_id)
            .order_by(AnalysisTerm.weighted_score.desc())
            .limit(100)
        )
    ).all()
    topics = (
        await service.session.scalars(
            select(AnalysisTopic)
            .where(AnalysisTopic.analysis_id == analysis_id)
            .order_by(AnalysisTopic.topic_index)
        )
    ).all()
    topic_points: list[TopicPoint] = []
    for topic in topics:
        topic_terms = (
            await service.session.execute(
                select(AnalysisTerm.display_term)
                .join(AnalysisTopicTerm, AnalysisTopicTerm.analysis_term_id == AnalysisTerm.id)
                .where(AnalysisTopicTerm.topic_id == topic.id)
                .order_by(AnalysisTopicTerm.rank)
            )
        ).scalars().all()
        representative_pmids = (
            await service.session.execute(
                select(Publication.pmid)
                .join(
                    AnalysisTopicPublication,
                    AnalysisTopicPublication.publication_id == Publication.id,
                )
                .where(
                    AnalysisTopicPublication.topic_id == topic.id,
                    AnalysisTopicPublication.is_representative.is_(True),
                )
                .order_by(AnalysisTopicPublication.rank)
            )
        ).scalars().all()
        topic_points.append(
            TopicPoint(
                id=topic.id,
                index=topic.topic_index,
                name=topic.name_zh,
                summary=topic.summary_zh,
                publication_count=topic.publication_count,
                share=float(topic.share),
                method=topic.clustering_method,
                confidence=float(topic.confidence) if topic.confidence is not None else None,
                terms=list(topic_terms),
                representative_pmids=list(representative_pmids),
            )
        )
    return TopicsResponse(
        analysis_id=analysis_id,
        terms=[
            TermPoint(
                term=row.display_term,
                document_count=row.document_count,
                weighted_score=float(row.weighted_score),
                sources=row.source_breakdown,
            )
            for row in terms
        ],
        topics=topic_points,
    )


@router.get("/analyses/{analysis_id}/publications", response_model=PublicationList)
async def get_publications(
    analysis_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: AnalysisService = Depends(_service),
) -> PublicationList:
    await service.ensure_ready(analysis_id)
    condition = (
        AnalysisPublication.analysis_id == analysis_id,
        AnalysisPublication.representative_rank.is_not(None),
    )
    total = await service.session.scalar(
        select(func.count()).select_from(AnalysisPublication).where(*condition)
    )
    rows = (
        await service.session.execute(
            select(AnalysisPublication, Publication)
            .join(Publication, Publication.id == AnalysisPublication.publication_id)
            .where(*condition)
            .order_by(AnalysisPublication.representative_rank)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    publication_ids = [publication.id for _, publication in rows]
    doi_rows = (
        await service.session.execute(
            select(PublicationIdentifier.publication_id, PublicationIdentifier.identifier_value).where(
                PublicationIdentifier.publication_id.in_(publication_ids),
                PublicationIdentifier.identifier_type == "doi",
            )
        )
    ).all()
    doi_by_publication = dict(doi_rows)
    return PublicationList(
        analysis_id=analysis_id,
        items=[
            PublicationPoint(
                pmid=publication.pmid,
                title=publication.title,
                abstract=publication.abstract_text,
                journal=publication.journal_title,
                publication_date=publication.publication_date.isoformat() if publication.publication_date else None,
                doi=doi_by_publication.get(publication.id),
                rank=association.representative_rank,
                score=float(association.representative_score) if association.representative_score is not None else None,
                score_components=association.score_components,
                scoring_version=association.scoring_version,
            )
            for association, publication in rows
        ],
        page=page,
        page_size=page_size,
        total=int(total or 0),
        disclaimer="代表性评分不是期刊影响因子；PubMed 可见引用关系覆盖不完整。",
    )


@router.get("/analyses/{analysis_id}/report", response_model=ReportResponse)
async def get_report(
    analysis_id: UUID,
    service: AnalysisService = Depends(_service),
) -> ReportResponse:
    analysis = await service.ensure_ready(analysis_id)
    report = await service.session.scalar(
        select(AnalysisReport).where(AnalysisReport.analysis_id == analysis_id)
    )
    if report is None:
        from app.api.errors import ApiError

        raise ApiError(500, "REPORT_MISSING", "报告缺失", "分析已完成但没有报告记录。")
    sections = (
        await service.session.scalars(
            select(AnalysisReportSection)
            .where(AnalysisReportSection.report_id == report.id)
            .order_by(AnalysisReportSection.position)
        )
    ).all()
    return ReportResponse(
        analysis_id=analysis_id,
        title=report.title,
        body_markdown=report.body_markdown,
        generation_mode=report.generation_mode,
        ai_status=analysis.ai_status,
        model=report.model_name,
        sections=[
            ReportSectionResponse(
                key=section.section_key,
                heading=section.heading,
                content=section.content,
                evidence_pmids=section.evidence_pmids,
                evidence_status=section.evidence_status,
            )
            for section in sections
        ],
        limitations=report.limitations,
        disclaimer="AI 辅助生成，不构成医疗建议。",
    )


@health_router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get("/ready", response_model=HealthResponse)
async def readiness(
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)
) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok", worker_enabled=settings.worker_enabled)

