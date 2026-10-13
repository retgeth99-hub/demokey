from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

REPORT_SECTION_KEYS = (
    "overview",
    "year_trend",
    "research_directions",
    "representative_findings",
    "limitations_and_outlook",
)


class ReportSectionPayload(BaseModel):
    key: str
    heading: str
    content: str = Field(min_length=1, max_length=1200)
    evidence_pmids: list[int] = Field(default_factory=list, max_length=50)


class TopicLabelPayload(BaseModel):
    index: int = Field(ge=1, le=20)
    name_zh: str = Field(min_length=1, max_length=100)
    summary_zh: str = Field(min_length=1, max_length=300)


class ReportPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sections: list[ReportSectionPayload] = Field(min_length=5, max_length=5)
    topic_labels: list[TopicLabelPayload] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def fixed_sections(self) -> ReportPayload:
        if tuple(section.key for section in self.sections) != REPORT_SECTION_KEYS:
            raise ValueError("report sections must use the fixed order")
        return self


def validate_evidence(report: ReportPayload, allowed_pmids: set[int]) -> None:
    invalid = {
        pmid
        for section in report.sections
        for pmid in section.evidence_pmids
        if pmid not in allowed_pmids
    }
    if invalid:
        raise ValueError(f"report referenced unknown PMIDs: {sorted(invalid)}")


def template_report(
    query: str,
    total_hits: int,
    sample_count: int,
    year_summary: str,
    topic_summary: str,
    evidence_pmids: list[int],
) -> ReportPayload:
    fallback_pmids = evidence_pmids[:5]
    sections = [
        ReportSectionPayload(
            key="overview",
            heading="领域概况",
            content=f"PubMed 对“{query}”共返回约 {total_hits} 条结果，本次按照预设上限抽取 {sample_count} 篇文献进行分析。以下结论仅反映该分析样本。",
            evidence_pmids=fallback_pmids,
        ),
        ReportSectionPayload(
            key="year_trend",
            heading="年度趋势",
            content=year_summary or "当前样本的发表年份信息不足，暂不能形成稳定的年度趋势判断。",
            evidence_pmids=fallback_pmids,
        ),
        ReportSectionPayload(
            key="research_directions",
            heading="主要研究方向",
            content=topic_summary or "当前样本的主题词覆盖不足，建议扩大样本或等待新文献完成 MeSH 编目后重新分析。",
            evidence_pmids=fallback_pmids,
        ),
        ReportSectionPayload(
            key="representative_findings",
            heading="代表性发现",
            content="代表性文献依据 PubMed 相关度、可见被引信号、发表时间、文献类型和 MeSH 匹配度综合筛选；该排名用于快速定位线索，不等同于正式影响因子排名。",
            evidence_pmids=evidence_pmids[:10],
        ),
        ReportSectionPayload(
            key="limitations_and_outlook",
            heading="局限与趋势",
            content="PubMed 的作者单位、主题词和引用关系均可能缺失或延迟更新；国家分布来自第一作者单位推断，引用覆盖也并不完整。后续应结合人工阅读和授权指标源验证重要结论。",
            evidence_pmids=fallback_pmids,
        ),
    ]
    return ReportPayload(
        title=f"“{query}”领域文献简报",
        sections=sections,
        limitations=["AI 辅助生成，不构成医疗建议。", "统计结果仅代表当前检索与抽样范围。"],
    )

