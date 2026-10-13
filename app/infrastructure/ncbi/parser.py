from __future__ import annotations

import re
from datetime import date

from lxml import etree

from app.domain.publications import (
    ParsedAffiliation,
    ParsedContributor,
    ParsedKeyword,
    ParsedMesh,
    ParsedPublication,
    ParsedPublicationType,
)

PARSER_VERSION = "pubmed-xml-v1"
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _text(node: etree._Element | None) -> str | None:
    if node is None:
        return None
    value = "".join(node.itertext()).strip()
    return re.sub(r"\s+", " ", value) or None


def _first(node: etree._Element, xpath: str) -> etree._Element | None:
    matches = node.xpath(xpath)
    return matches[0] if matches else None


def _date(article: etree._Element) -> tuple[date | None, int | None, str]:
    candidates = article.xpath(
        ".//Article/Journal/JournalIssue/PubDate | .//ArticleDate | .//PubMedPubDate[@PubStatus='pubmed']"
    )
    for node in candidates:
        year_text = _text(_first(node, "./Year"))
        month_text = _text(_first(node, "./Month"))
        day_text = _text(_first(node, "./Day"))
        medline_date = _text(_first(node, "./MedlineDate"))
        if not year_text and medline_date:
            match = re.search(r"\b(18|19|20)\d{2}\b", medline_date)
            year_text = match.group(0) if match else None
        if not year_text or not year_text.isdigit():
            continue
        year = int(year_text)
        month = 1
        day = 1
        precision = "year"
        if month_text:
            month = int(month_text) if month_text.isdigit() else MONTHS.get(month_text[:3].casefold(), 1)
            precision = "month"
        if day_text and day_text.isdigit():
            day = int(day_text)
            precision = "day"
        try:
            return date(year, max(1, min(month, 12)), max(1, min(day, 28))), year, precision
        except ValueError:
            return None, year, "year"
    return None, None, "unknown"


def _abstract(article: etree._Element) -> tuple[str | None, list[dict[str, str]]]:
    sections: list[dict[str, str]] = []
    for node in article.xpath(".//Article/Abstract/AbstractText"):
        content = _text(node)
        if not content:
            continue
        label = node.get("Label") or node.get("NlmCategory") or ""
        sections.append({"label": label, "text": content})
    if not sections:
        return None, []
    combined = "\n".join(
        f"{section['label']}: {section['text']}" if section["label"] else section["text"]
        for section in sections
    )
    return combined, sections


def _contributors(article: etree._Element) -> list[ParsedContributor]:
    output: list[ParsedContributor] = []
    for position, author in enumerate(article.xpath(".//Article/AuthorList/Author"), start=1):
        orcid: str | None = None
        for identifier in author.xpath("./Identifier"):
            if (identifier.get("Source") or "").casefold() == "orcid":
                orcid = _text(identifier)
        affiliations = [
            ParsedAffiliation(value)
            for value in (_text(node) for node in author.xpath("./AffiliationInfo/Affiliation"))
            if value
        ]
        output.append(
            ParsedContributor(
                position=position,
                last_name=_text(_first(author, "./LastName")),
                fore_name=_text(_first(author, "./ForeName")),
                initials=_text(_first(author, "./Initials")),
                collective_name=_text(_first(author, "./CollectiveName")),
                orcid=orcid,
                affiliations=affiliations,
            )
        )
    return output


def _mesh_terms(article: etree._Element) -> list[ParsedMesh]:
    output: list[ParsedMesh] = []
    for heading in article.xpath(".//MeshHeadingList/MeshHeading"):
        descriptor = _first(heading, "./DescriptorName")
        name = _text(descriptor)
        if descriptor is None or not name:
            continue
        qualifiers = []
        for qualifier in heading.xpath("./QualifierName"):
            qualifiers.append(
                {
                    "ui": qualifier.get("UI") or "",
                    "name": _text(qualifier) or "",
                    "major": qualifier.get("MajorTopicYN") == "Y",
                }
            )
        output.append(
            ParsedMesh(
                ui=descriptor.get("UI") or name,
                name=name,
                is_major=descriptor.get("MajorTopicYN") == "Y",
                qualifiers=qualifiers,
            )
        )
    return output


def _keywords(article: etree._Element) -> list[ParsedKeyword]:
    output: list[ParsedKeyword] = []
    for keyword_list in article.xpath(".//KeywordList"):
        owner = keyword_list.get("Owner") or ""
        for keyword in keyword_list.xpath("./Keyword"):
            value = _text(keyword)
            if value:
                output.append(
                    ParsedKeyword(value, keyword.get("MajorTopicYN") == "Y", owner)
                )
    return output


def parse_pubmed_xml(payload: bytes) -> list[ParsedPublication]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)
    root = etree.fromstring(payload, parser=parser)
    output: list[ParsedPublication] = []
    for article in root.xpath(".//PubmedArticle"):
        pmid_text = _text(_first(article, "./MedlineCitation/PMID"))
        if not pmid_text or not pmid_text.isdigit():
            continue
        title = _text(_first(article, ".//Article/ArticleTitle")) or ""
        abstract_text, abstract_sections = _abstract(article)
        publication_date, publication_year, precision = _date(article)
        issn_print: str | None = None
        issn_electronic: str | None = None
        for issn in article.xpath(".//Article/Journal/ISSN"):
            if issn.get("IssnType") == "Electronic":
                issn_electronic = _text(issn)
            else:
                issn_print = _text(issn)
        identifiers: dict[str, str] = {}
        for identifier in article.xpath(".//PubmedData/ArticleIdList/ArticleId"):
            value = _text(identifier)
            kind = (identifier.get("IdType") or "other").casefold()
            if value:
                identifiers[kind] = value
        publication_types = [
            ParsedPublicationType(node.get("UI") or (_text(node) or ""), _text(node) or "")
            for node in article.xpath(".//Article/PublicationTypeList/PublicationType")
            if _text(node)
        ]
        type_names = {item.name.casefold() for item in publication_types}
        output.append(
            ParsedPublication(
                pmid=int(pmid_text),
                title=title,
                abstract_text=abstract_text,
                abstract_sections=abstract_sections,
                journal_title=_text(_first(article, ".//Article/Journal/Title")),
                journal_abbreviation=_text(_first(article, ".//MedlineJournalInfo/MedlineTA")),
                issn_print=issn_print,
                issn_electronic=issn_electronic,
                volume=_text(_first(article, ".//Article/Journal/JournalIssue/Volume")),
                issue=_text(_first(article, ".//Article/Journal/JournalIssue/Issue")),
                pagination=_text(_first(article, ".//Article/Pagination/MedlinePgn")),
                languages=[value for value in (_text(node) for node in article.xpath(".//Article/Language")) if value],
                publication_date=publication_date,
                publication_year=publication_year,
                date_precision=precision,
                identifiers=identifiers,
                contributors=_contributors(article),
                mesh_terms=_mesh_terms(article),
                keywords=_keywords(article),
                publication_types=publication_types,
                is_retracted="retracted publication" in type_names,
                is_corrected="published erratum" in type_names,
                quality_flags={
                    "missing_title": not bool(title),
                    "missing_abstract": not bool(abstract_text),
                    "missing_mesh": not bool(_mesh_terms(article)),
                },
            )
        )
    return output


def parse_elink_cited_counts(payload: bytes) -> dict[int, int | None]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)
    root = etree.fromstring(payload, parser=parser)
    result: dict[int, int | None] = {}
    for link_set in root.xpath(".//LinkSet"):
        source = _text(_first(link_set, "./IdList/Id"))
        if not source or not source.isdigit():
            continue
        links = link_set.xpath("./LinkSetDb[LinkName='pubmed_pubmed_citedin']/Link/Id")
        result[int(source)] = len(links)
    return result

