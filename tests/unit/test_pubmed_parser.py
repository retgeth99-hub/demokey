from app.infrastructure.ncbi.parser import parse_elink_cited_counts, parse_pubmed_xml

PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345</PMID>
      <Article>
        <Journal>
          <ISSN IssnType="Electronic">1234-5678</ISSN>
          <JournalIssue><PubDate><Year>2025</Year><Month>Oct</Month><Day>7</Day></PubDate></JournalIssue>
          <Title>Journal of Tests</Title>
        </Journal>
        <ArticleTitle>A <i>structured</i> PubMed article</ArticleTitle>
        <Abstract><AbstractText Label="BACKGROUND">Background text.</AbstractText></Abstract>
        <AuthorList>
          <Author><LastName>Li</LastName><ForeName>Ming</ForeName><AffiliationInfo><Affiliation>Chengdu, China.</Affiliation></AffiliationInfo></Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
      </Article>
      <MeshHeadingList><MeshHeading><DescriptorName UI="D000544" MajorTopicYN="Y">Alzheimer Disease</DescriptorName></MeshHeading></MeshHeadingList>
      <KeywordList Owner="NOTNLM"><Keyword>biomarker</Keyword></KeywordList>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/test</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_parses_pubmed_xml() -> None:
    result = parse_pubmed_xml(PUBMED_XML)
    assert len(result) == 1
    article = result[0]
    assert article.pmid == 12345
    assert article.title == "A structured PubMed article"
    assert article.publication_year == 2025
    assert article.identifiers["doi"] == "10.1/test"
    assert article.mesh_terms[0].is_major is True
    assert article.contributors[0].affiliations[0].text == "Chengdu, China."


def test_parses_cited_counts() -> None:
    payload = b"""<eLinkResult><LinkSet><IdList><Id>123</Id></IdList><LinkSetDb><LinkName>pubmed_pubmed_citedin</LinkName><Link><Id>9</Id></Link><Link><Id>10</Id></Link></LinkSetDb></LinkSet></eLinkResult>"""
    assert parse_elink_cited_counts(payload) == {123: 2}

