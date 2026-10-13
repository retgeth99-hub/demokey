from __future__ import annotations

import re
from dataclasses import dataclass

import pycountry

PARSER_VERSION = "country-rules-v1"

ALIASES: dict[str, tuple[str, str]] = {
    "u.s.a": ("US", "United States"),
    "usa": ("US", "United States"),
    "united states": ("US", "United States"),
    "u.s.": ("US", "United States"),
    "uk": ("GB", "United Kingdom"),
    "u.k.": ("GB", "United Kingdom"),
    "england": ("GB", "United Kingdom"),
    "scotland": ("GB", "United Kingdom"),
    "wales": ("GB", "United Kingdom"),
    "south korea": ("KR", "Korea, Republic of"),
    "republic of korea": ("KR", "Korea, Republic of"),
    "north korea": ("KP", "Korea, Democratic People's Republic of"),
    "russia": ("RU", "Russian Federation"),
    "taiwan": ("TW", "Taiwan"),
    "iran": ("IR", "Iran, Islamic Republic of"),
    "vietnam": ("VN", "Viet Nam"),
}


@dataclass(frozen=True, slots=True)
class CountryMatch:
    code: str | None
    name: str | None
    confidence: float | None
    rule_id: str | None


def _bounded_contains(text: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle.lower())}(?![a-z])", text.lower()) is not None


def parse_country(affiliation: str | None) -> CountryMatch:
    if not affiliation:
        return CountryMatch(None, None, None, None)
    lowered = affiliation.casefold()
    for alias in sorted(ALIASES, key=len, reverse=True):
        if _bounded_contains(lowered, alias):
            code, name = ALIASES[alias]
            return CountryMatch(code, name, 0.95, f"alias:{alias}")

    candidates: list[tuple[int, str, str]] = []
    for country in pycountry.countries:
        names = {country.name}
        official = getattr(country, "official_name", None)
        common = getattr(country, "common_name", None)
        if official:
            names.add(official)
        if common:
            names.add(common)
        for name in names:
            if _bounded_contains(lowered, name.casefold()):
                candidates.append((len(name), country.alpha_2, country.name))
    if candidates:
        _, code, name = max(candidates)
        return CountryMatch(code, name, 0.9, "iso-country-name")
    return CountryMatch(None, None, None, None)

