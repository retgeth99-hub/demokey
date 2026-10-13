import pytest

from app.domain.reports import template_report, validate_evidence


def test_template_report_has_fixed_sections_and_valid_evidence() -> None:
    report = template_report("diabetes", 100, 20, "2025年10篇", "代谢、干预", [1, 2])
    assert len(report.sections) == 5
    validate_evidence(report, {1, 2})
    assert "不构成医疗建议" in report.limitations[0]


def test_evidence_validation_rejects_unknown_pmid() -> None:
    report = template_report("diabetes", 100, 20, "", "", [1])
    report.sections[0].evidence_pmids = [999]
    with pytest.raises(ValueError, match="unknown PMIDs"):
        validate_evidence(report, {1})

