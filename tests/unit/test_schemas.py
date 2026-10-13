import pytest
from pydantic import ValidationError

from app.api.schemas import AnalysisCreate


def test_analysis_request_rejects_invalid_limits() -> None:
    with pytest.raises(ValidationError):
        AnalysisCreate(query="test", metadata_limit=10, abstract_limit=11)


def test_analysis_request_normalizes_filter_lists() -> None:
    payload = AnalysisCreate(query="test", languages=["eng", "eng", " chi "])
    assert payload.languages == ["chi", "eng"]

