from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.api.schemas import AnalysisCreate
from app.application.analyses import AnalysisService
from app.core.config import get_settings
from app.domain.reports import template_report
from app.infrastructure.db.models import Analysis, AnalysisReport, AnalysisTopic, Publication
from app.infrastructure.db.session import SessionFactory
from app.infrastructure.deepseek.client import GeneratedReport
from app.infrastructure.ncbi.client import BinaryResult, SearchResult
from app.main import app
from app.worker.pipeline import AnalysisPipeline

pytestmark = pytest.mark.asyncio(loop_scope="session")


def pubmed_xml(pmids: list[int]) -> bytes:
    articles = []
    for index, pmid in enumerate(pmids):
        group = "Biomarkers" if index < 2 else "Immunotherapy"
        disease = "Alzheimer Disease" if index < 2 else "Neoplasms"
        articles.append(
            f"""
            <PubmedArticle>
              <MedlineCitation>
                <PMID>{pmid}</PMID>
                <Article>
                  <Journal><JournalIssue><PubDate><Year>2025</Year><Month>1</Month><Day>2</Day></PubDate></JournalIssue><Title>Test Journal</Title></Journal>
                  <ArticleTitle>Study {pmid} about {group}</ArticleTitle>
                  <Abstract><AbstractText>Long structured abstract for {group} and clinical outcomes in a representative study.</AbstractText></Abstract>
                  <AuthorList><Author><LastName>Li</LastName><ForeName>Ming</ForeName><AffiliationInfo><Affiliation>Chengdu, China.</Affiliation></AffiliationInfo></Author></AuthorList>
                  <Language>eng</Language>
                  <PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
                </Article>
                <MeshHeadingList>
                  <MeshHeading><DescriptorName UI="D{index}01" MajorTopicYN="Y">{group}</DescriptorName></MeshHeading>
                  <MeshHeading><DescriptorName UI="D{index}02">{disease}</DescriptorName></MeshHeading>
                </MeshHeadingList>
                <KeywordList Owner="NOTNLM"><Keyword>{group}</Keyword></KeywordList>
              </MedlineCitation>
              <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/{pmid}</ArticleId></ArticleIdList></PubmedData>
            </PubmedArticle>
            """
        )
    return f"<PubmedArticleSet>{''.join(articles)}</PubmedArticleSet>".encode()


class FakeNcbi:
    async def close(self) -> None:
        return None

    async def search(self, term: str, retmax: int, sort: str) -> SearchResult:
        ids = [1001, 1002, 1003, 1004]
        payload = json.dumps({"esearchresult": {"count": "4", "idlist": ids}}).encode()
        return SearchResult(4, ids, term, "history", "1", payload, 2, "search-fp")

    async def fetch(self, ids: list[int]) -> BinaryResult:
        return BinaryResult(pubmed_xml(ids), 2, f"fetch-{'-'.join(map(str, ids))}", 200)

    async def cited_by(self, ids: list[int]) -> BinaryResult:
        sets = "".join(
            f"<LinkSet><IdList><Id>{pmid}</Id></IdList><LinkSetDb><LinkName>pubmed_pubmed_citedin</LinkName><Link><Id>{pmid + 10000}</Id></Link></LinkSetDb></LinkSet>"
            for pmid in ids
        )
        return BinaryResult(f"<eLinkResult>{sets}</eLinkResult>".encode(), 2, "elink-fp", 200)


class FakeDeepSeek:
    async def close(self) -> None:
        return None

    async def generate_report(
        self, evidence: dict[str, object], allowed_pmids: set[int]
    ) -> GeneratedReport:
        topics = evidence["topics"]
        assert isinstance(topics, list)
        for topic in topics:
            assert isinstance(topic, dict)
            assert set(topic["pmids"]) <= allowed_pmids
        report = template_report(
            str(evidence["query"]),
            int(evidence["total_hits"]),
            int(evidence["sample_count"]),
            "2025年4篇",
            "生物标志物；免疫治疗",
            sorted(allowed_pmids),
        )
        return GeneratedReport(report, "fake-deepseek", {"total_tokens": 100}, "valid")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_database() -> None:
    async with SessionFactory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE analysis, publication, mesh_term, publication_type "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.mark.integration
async def test_full_pipeline_and_result_api() -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        service = AnalysisService(session, settings)
        analysis, cached = await service.create(
            AnalysisCreate(
                query="Alzheimer biomarkers",
                metadata_limit=10,
                abstract_limit=10,
                report_evidence_limit=2,
            )
        )
        analysis_id = analysis.id
        assert cached is False

    pipeline = AnalysisPipeline(
        SessionFactory,
        settings,
        ncbi_client=FakeNcbi(),  # type: ignore[arg-type]
        deepseek_client=FakeDeepSeek(),  # type: ignore[arg-type]
    )
    await pipeline.run(analysis_id)

    async with SessionFactory() as session:
        result = await session.get(Analysis, analysis_id)
        assert result is not None
        assert result.status == "succeeded"
        assert result.sampled_publication_count == 4
        assert result.ai_status == "succeeded"
        assert len((await session.scalars(select(Publication))).all()) == 4
        assert len((await session.scalars(select(AnalysisTopic))).all()) >= 1
        report = await session.scalar(
            select(AnalysisReport).where(AnalysisReport.analysis_id == analysis_id)
        )
        assert report is not None
        assert report.model_name == "fake-deepseek"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status_response = await client.get(f"/api/v1/analyses/{analysis_id}")
        assert status_response.status_code == 200
        overview = await client.get(f"/api/v1/analyses/{analysis_id}/overview")
        assert overview.status_code == 200
        assert overview.json()["sampled_publication_count"] == 4
        publications = await client.get(f"/api/v1/analyses/{analysis_id}/publications")
        assert publications.status_code == 200
        assert publications.json()["total"] == 4
        report_response = await client.get(f"/api/v1/analyses/{analysis_id}/report")
        assert report_response.status_code == 200
        assert len(report_response.json()["sections"]) == 5


@pytest.mark.integration
async def test_completed_analysis_is_reused_within_cache_window() -> None:
    settings = get_settings()
    payload = AnalysisCreate(query="cache test", metadata_limit=10, abstract_limit=5)
    async with SessionFactory() as session:
        service = AnalysisService(session, settings)
        original, _ = await service.create(payload)
        original.status = "succeeded"
        original.completed_at = datetime.now(UTC)
        await session.commit()

    async with SessionFactory() as session:
        service = AnalysisService(session, settings)
        reused, cache_hit = await service.create(payload)
        assert cache_hit is True
        assert reused.id == original.id

