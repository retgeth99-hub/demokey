from app.domain.query import AnalysisQuery, build_pubmed_term, normalize_query_text, query_hash


def test_query_normalization_and_hash_are_stable() -> None:
    first = AnalysisQuery(
        query="  diabetes   AND therapy ",
        start_year=2020,
        end_year=2026,
        languages=("eng", "chi"),
        publication_types=("Clinical Trial",),
        sort="relevance",
        metadata_limit=100,
        abstract_limit=50,
        report_evidence_limit=30,
    )
    second = AnalysisQuery(
        query="diabetes AND therapy",
        start_year=2020,
        end_year=2026,
        languages=("chi", "eng"),
        publication_types=("Clinical Trial",),
        sort="relevance",
        metadata_limit=100,
        abstract_limit=50,
        report_evidence_limit=30,
    )
    assert normalize_query_text(first.query) == "diabetes AND therapy"
    assert query_hash(first) == query_hash(second)
    term = build_pubmed_term(first)
    assert '"2020"[Date - Publication] : "2026"[Date - Publication]' in term
    assert '"eng"[Language]' in term


def test_hash_changes_when_analysis_limit_changes() -> None:
    base = dict(
        query="cancer",
        start_year=None,
        end_year=None,
        languages=(),
        publication_types=(),
        sort="relevance",
        abstract_limit=50,
        report_evidence_limit=30,
    )
    assert query_hash(AnalysisQuery(metadata_limit=100, **base)) != query_hash(
        AnalysisQuery(metadata_limit=101, **base)
    )

