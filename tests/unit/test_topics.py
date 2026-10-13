from datetime import date

from app.domain.publications import ParsedMesh, ParsedPublication
from app.domain.topics import cluster_topics, extract_terms


def publication(pmid: int, terms: list[str]) -> ParsedPublication:
    return ParsedPublication(
        pmid=pmid,
        title=f"Study {pmid}",
        abstract_text="A sufficiently long abstract about biomarkers and clinical outcomes.",
        abstract_sections=[],
        journal_title=None,
        journal_abbreviation=None,
        issn_print=None,
        issn_electronic=None,
        volume=None,
        issue=None,
        pagination=None,
        languages=["eng"],
        publication_date=date(2025, 1, 1),
        publication_year=2025,
        date_precision="day",
        identifiers={},
        contributors=[],
        mesh_terms=[ParsedMesh(f"D{i}", term, i == 0) for i, term in enumerate(terms)],
        keywords=[],
        publication_types=[],
    )


def test_mesh_terms_and_clusters_are_generated() -> None:
    publications = [
        publication(1, ["Biomarkers", "Alzheimer Disease"]),
        publication(2, ["Biomarkers", "Alzheimer Disease"]),
        publication(3, ["Immunotherapy", "Neoplasms"]),
        publication(4, ["Immunotherapy", "Neoplasms"]),
    ]
    terms = extract_terms(publications)
    assert terms[0].weighted_score >= terms[-1].weighted_score
    clusters = cluster_topics(publications)
    assert clusters
    assert clusters[0].method == "mesh_cooccurrence"

