from app.domain.regions import parse_country


def test_parses_common_country_aliases() -> None:
    result = parse_country("Department of Medicine, Stanford University, CA, USA.")
    assert result.code == "US"
    assert result.confidence == 0.95


def test_parses_official_country_name() -> None:
    result = parse_country("University Hospital, Zurich, Switzerland")
    assert result.code == "CH"


def test_unknown_affiliation_stays_unknown() -> None:
    result = parse_country("Department of Medicine")
    assert result.code is None
    assert result.confidence is None

