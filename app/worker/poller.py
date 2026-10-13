from __future__ import annotations

import asyncio
import logging
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.db.models import Analysis, AnalysisJob, AnalysisStageRun, RawIngestBatch
from app.infrastructure.ncbi.client import UpstreamError
from app.worker.pipeline import AnalysisCancelled, AnalysisPipeline

logger = logging.getLogger(__name__)


class JobPoller:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        pipeline: AnalysisPipeline,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.pipeline = pipeline
        self.worker_id = f"{socket.gethostname()}-{uuid4()}"
        self._stop = asyncio.Event()
        self._last_cleanup_at: datetime | None = None

    async def stop(self) -> None:
        self._stop.set()
        await self.pipeline.close()

    async def _claim(self) -> tuple[UUID, UUID] | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                job = await session.scalar(
                    select(AnalysisJob)
                    .where(
                        or_(
                            and_(AnalysisJob.status == "queued", AnalysisJob.available_at <= now),
                            and_(
                                AnalysisJob.status == "running",
                                AnalysisJob.lease_expires_at < now,
                            ),
                        )
                    )
                    .order_by(AnalysisJob.priority, AnalysisJob.available_at, AnalysisJob.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    return None
                job.status = "running"
                job.lease_owner = self.worker_id
                job.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
                job.heartbeat_at = now
                job.attempt_count += 1
                analysis = await session.get(Analysis, job.analysis_id)
                if analysis is None:
                    job.status = "failed"
                    job.last_error_code = "ANALYSIS_NOT_FOUND"
                    return None
                analysis.status = "running"
                analysis.started_at = analysis.started_at or now
                return job.id, job.analysis_id

    async def _cancelled(self, job_id: UUID, analysis_id: UUID) -> None:
        async with self.session_factory() as session:
            job = await session.get(AnalysisJob, job_id)
            analysis = await session.get(Analysis, analysis_id)
            if job and analysis:
                job.status = "cancelled"
                job.lease_owner = None
                job.lease_expires_at = None
                analysis.status = "cancelled"
                analysis.phase = "cancelled"
                analysis.completed_at = datetime.now(UTC)
                stages = (
                    await session.scalars(
                        select(AnalysisStageRun).where(
                            AnalysisStageRun.analysis_id == analysis_id,
                            AnalysisStageRun.status == "running",
                        )
                    )
                ).all()
                for stage in stages:
                    stage.status = "cancelled"
                    stage.finished_at = analysis.completed_at
                await session.commit()

    async def _failed(self, job_id: UUID, analysis_id: UUID, exc: Exception) -> None:
        async with self.session_factory() as session:
            job = await session.get(AnalysisJob, job_id)
            analysis = await session.get(Analysis, analysis_id)
            if job is None or analysis is None:
                return
            retryable = isinstance(exc, UpstreamError) and exc.retryable
            code = exc.code if isinstance(exc, UpstreamError) else "ANALYSIS_INTERNAL_ERROR"
            detail = exc.detail if isinstance(exc, UpstreamError) else "分析任务发生内部错误。"
            if retryable and job.attempt_count < job.max_attempts:
                job.status = "queued"
                job.available_at = datetime.now(UTC) + timedelta(seconds=2 ** job.attempt_count)
                analysis.status = "queued"
            else:
                job.status = "failed"
                analysis.status = "failed"
                analysis.completed_at = datetime.now(UTC)
            job.last_error_code = code
            job.last_error_detail = detail
            job.lease_owner = None
            job.lease_expires_at = None
            analysis.error_code = code
            analysis.error_detail = detail
            analysis.retryable = retryable
            stages = (
                await session.scalars(
                    select(AnalysisStageRun).where(
                        AnalysisStageRun.analysis_id == analysis_id,
                        AnalysisStageRun.status == "running",
                    )
                )
            ).all()
            for stage in stages:
                stage.status = "failed"
                stage.error_code = code
                stage.finished_at = datetime.now(UTC)
            await session.commit()

    async def _cleanup_expired_data(self) -> None:
        now = datetime.now(UTC)
        if self._last_cleanup_at and now - self._last_cleanup_at < timedelta(hours=1):
            return
        async with self.session_factory() as session:
            await session.execute(delete(RawIngestBatch).where(RawIngestBatch.expires_at < now))
            await session.execute(
                delete(Analysis).where(
                    Analysis.deleted_at.is_not(None),
                    Analysis.deleted_at < now - timedelta(days=7),
                )
            )
            await session.commit()
        self._last_cleanup_at = now

    async def _succeeded(self, job_id: UUID) -> None:
        async with self.session_factory() as session:
            job = await session.get(AnalysisJob, job_id)
            if job:
                job.status = "succeeded"
                job.current_stage = "completed"
                job.lease_owner = None
                job.lease_expires_at = None
                await session.commit()

    async def run_forever(self) -> None:
        logger.info("analysis worker started")
        while not self._stop.is_set():
            await self._cleanup_expired_data()
            claimed = await self._claim()
            if claimed is None:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.worker_poll_seconds
                    )
                except TimeoutError:
                    pass
                continue
            job_id, analysis_id = claimed
            try:
                await self.pipeline.run(analysis_id)
                await self._succeeded(job_id)
            except AnalysisCancelled:
                await self._cancelled(job_id, analysis_id)
            except Exception as exc:
                logger.exception("analysis job failed", extra={"analysis_id": str(analysis_id)})
                await self._failed(job_id, analysis_id, exc)
        logger.info("analysis worker stopped")

