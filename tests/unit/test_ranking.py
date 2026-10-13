from datetime import date

from app.domain.ranking import RankingInput, rank_publications


def test_ranking_reallocates_missing_citation_weight() -> None:
    items = [
        RankingInput(
            pmid=1,
            pubmed_rank=1,
            publication_date=date(2026, 1, 1),
            publication_types=("Meta-Analysis",),
            mesh_names=("Diabetes Mellitus",),
            major_mesh_names=("Diabetes Mellitus",),
            visible_citations=None,
        ),
        RankingInput(
            pmid=2,
            pubmed_rank=2,
            publication_date=date(2023, 1, 1),
            publication_types=("Letter",),
            mesh_names=("Other",),
            major_mesh_names=(),
            visible_citations=0,
        ),
    ]
    results = rank_publications(items, {"diabetes mellitus"}, date(2026, 10, 12))
    assert results[0].pmid == 1
    first = next(result for result in results if result.pmid == 1)
    assert "citation" in first.missing_signals
    assert abs(sum(first.effective_weights.values()) - 1) < 1e-9
    assert 0 <= first.score <= 1

