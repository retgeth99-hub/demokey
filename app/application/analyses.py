from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.schemas import AnalysisCreate
from app.core.config import Settings
from app.domain.query import AnalysisQuery, normalize_query_text, query_hash, stable_query_payload
from app.infrastructure.db.models import Analysis, AnalysisJob


class AnalysisService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def _domain_query(payload: AnalysisCreate) -> AnalysisQuery:
        return AnalysisQuery(
            query=payload.query,
            start_year=payload.start_year,
            end_year=payload.end_year,
            languages=tuple(payload.languages),
            publication_types=tuple(payload.publication_types),
            sort=payload.sort,
            metadata_limit=payload.metadata_limit,
            abstract_limit=payload.abstract_limit,
            report_evidence_limit=payload.report_evidence_limit,
        )

    async def create(self, payload: AnalysisCreate) -> tuple[Analysis, bool]:
        domain_query = self._domain_query(payload)
        fingerprint = query_hash(domain_query)
        if not payload.force_refresh and self.settings.analysis_cache_hours > 0:
            cutoff = datetime.now(UTC) - timedelta(hours=self.settings.analysis_cache_hours)
            cached = await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.query_hash == fingerprint,
                    Analysis.status == "succeeded",
                    Analysis.completed_at >= cutoff,
                    Analysis.deleted_at.is_(None),
                )
                .order_by(Analysis.completed_at.desc())
                .limit(1)
            )
            if cached is not None:
                return cached, True

        now = datetime.now(UTC)
        analysis = Analysis(
            query_text=payload.query,
            normalized_query=normalize_query_text(payload.query),
            query_hash=fingerprint,
            request_parameters=stable_query_payload(domain_query),
            start_year=payload.start_year,
            end_year=payload.end_year,
            sort_mode=payload.sort,
            metadata_limit=payload.metadata_limit,
            abstract_limit=payload.abstract_limit,
            report_evidence_limit=payload.report_evidence_limit,
            status="queued",
            progress_percent=Decimal("0"),
            algorithm_versions={
                "query": domain_query.algorithm_version,
                "ranking": "representative-v1",
                "regions": "country-rules-v1",
                "topics": "topics-v1",
            },
        )
        self.session.add(analysis)
        await self.session.flush()
        self.session.add(
            AnalysisJob(
                analysis_id=analysis.id,
                status="queued",
                available_at=now,
                stage_checkpoint={},
            )
        )
        await self.session.commit()
        await self.session.refresh(analysis)
        return analysis, False

    async def get(self, analysis_id: UUID, include_deleted: bool = False) -> Analysis:
        conditions = [Analysis.id == analysis_id]
        if not include_deleted:
            conditions.append(Analysis.deleted_at.is_(None))
        analysis = await self.session.scalar(select(Analysis).where(*conditions))
        if analysis is None:
            raise ApiError(404, "ANALYSIS_NOT_FOUND", "分析不存在", "未找到指定分析。")
        return analysis

    async def list(self, page: int, page_size: int) -> tuple[list[Analysis], int]:
        conditions = [Analysis.deleted_at.is_(None)]
        total = await self.session.scalar(select(func.count()).select_from(Analysis).where(*conditions))
        items = list(
            (
                await self.session.scalars(
                    select(Analysis)
                    .where(*conditions)
                    .order_by(Analysis.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, int(total or 0)

    async def cancel(self, analysis_id: UUID) -> Analysis:
        analysis = await self.get(analysis_id)
        if analysis.status in {"succeeded", "failed", "cancelled"}:
            raise ApiError(409, "ANALYSIS_TERMINAL", "分析已经结束", "终态分析不能取消。")
        now = datetime.now(UTC)
        job = await self.session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
        if analysis.status == "queued":
            analysis.status = "cancelled"
            analysis.phase = "cancelled"
            analysis.completed_at = now
            if job:
                job.status = "cancelled"
                job.cancel_requested_at = now
        else:
            analysis.status = "cancel_requested"
        if job and analysis.status == "cancel_requested":
            job.status = "cancel_requested"
            job.cancel_requested_at = now
        await self.session.commit()
        return analysis

    async def retry(self, analysis_id: UUID) -> Analysis:
        analysis = await self.get(analysis_id)
        if analysis.status != "failed" or not analysis.retryable:
            raise ApiError(409, "ANALYSIS_NOT_RETRYABLE", "分析不可重试", "只有可重试失败才能重新排队。")
        job = await self.session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
        if job is None:
            raise ApiError(409, "JOB_NOT_FOUND", "任务不存在", "分析任务记录缺失。")
        now = datetime.now(UTC)
        analysis.status = "queued"
        analysis.error_code = None
        analysis.error_detail = None
        analysis.retryable = False
        analysis.completed_at = None
        job.status = "queued"
        job.attempt_count = 0
        job.available_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.commit()
        return analysis

    async def soft_delete(self, analysis_id: UUID) -> None:
        analysis = await self.get(analysis_id)
        if analysis.status in {"queued", "running", "cancel_requested"}:
            raise ApiError(409, "ANALYSIS_ACTIVE", "分析仍在运行", "请先取消分析再删除。")
        analysis.deleted_at = datetime.now(UTC)
        await self.session.commit()

    async def ensure_ready(self, analysis_id: UUID) -> Analysis:
        analysis = await self.get(analysis_id)
        if analysis.status != "succeeded":
            raise ApiError(
                409,
                "ANALYSIS_NOT_READY",
                "分析尚未完成",
                f"当前状态为 {analysis.status}。",
                retryable=analysis.retryable,
                extra={"phase": analysis.phase, "progress_percent": float(analysis.progress_percent)},
            )
        return analysis

