from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

import networkx as nx
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

from app.domain.publications import ParsedPublication

TOPIC_VERSION = "topics-v1"
TERM_VERSION = "terms-v1"


@dataclass(frozen=True, slots=True)
class WeightedTerm:
    normalized: str
    display: str
    document_count: int
    raw_frequency: int
    weighted_score: float
    sources: dict[str, int]


@dataclass(frozen=True, slots=True)
class TopicCluster:
    index: int
    terms: tuple[str, ...]
    pmids: tuple[int, ...]
    method: str
    confidence: float | None
    parameters: dict[str, object]


def normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def extract_terms(publications: list[ParsedPublication], limit: int = 100) -> list[WeightedTerm]:
    weighted: Counter[str] = Counter()
    raw: Counter[str] = Counter()
    documents: Counter[str] = Counter()
    sources: dict[str, Counter[str]] = defaultdict(Counter)
    display: dict[str, str] = {}
    for publication in publications:
        seen: set[str] = set()
        for mesh in publication.mesh_terms:
            key = normalize_term(mesh.name)
            if not key:
                continue
            display.setdefault(key, mesh.name)
            source = "major_mesh" if mesh.is_major else "mesh"
            weight = 3 if mesh.is_major else 2
            weighted[key] += weight
            raw[key] += 1
            sources[key][source] += 1
            seen.add(key)
        for keyword in publication.keywords:
            key = normalize_term(keyword.text)
            if not key:
                continue
            display.setdefault(key, keyword.text)
            weighted[key] += 1
            raw[key] += 1
            sources[key]["keyword"] += 1
            seen.add(key)
        for key in seen:
            documents[key] += 1
    result = [
        WeightedTerm(
            normalized=key,
            display=display[key],
            document_count=documents[key],
            raw_frequency=raw[key],
            weighted_score=float(score),
            sources=dict(sources[key]),
        )
        for key, score in weighted.most_common(limit)
    ]
    return result


def _mesh_clusters(publications: list[ParsedPublication], max_topics: int) -> list[TopicCluster]:
    graph = nx.Graph()
    pmids_by_term: dict[str, set[int]] = defaultdict(set)
    for publication in publications:
        terms = sorted({normalize_term(item.name) for item in publication.mesh_terms if item.name})
        for term in terms:
            pmids_by_term[term].add(publication.pmid)
            graph.add_node(term)
        for index, left in enumerate(terms):
            for right in terms[index + 1 :]:
                if graph.has_edge(left, right):
                    graph[left][right]["weight"] += 1
                else:
                    graph.add_edge(left, right, weight=1)
    graph.remove_nodes_from([node for node in graph if len(pmids_by_term[node]) < 2])
    if graph.number_of_nodes() < 3 or graph.number_of_edges() == 0:
        return []
    communities = list(nx.community.greedy_modularity_communities(graph, weight="weight"))
    communities = sorted(communities, key=lambda group: (-len(group), sorted(group)[0]))[:max_topics]
    output: list[TopicCluster] = []
    for index, community in enumerate(communities, start=1):
        ranked_terms = sorted(
            community,
            key=lambda term: (-graph.degree(term, weight="weight"), term),
        )[:8]
        pmids = sorted({pmid for term in community for pmid in pmids_by_term[term]})
        output.append(
            TopicCluster(
                index=index,
                terms=tuple(ranked_terms),
                pmids=tuple(pmids),
                method="mesh_cooccurrence",
                confidence=min(1.0, len(pmids) / max(len(publications), 1) + 0.25),
                parameters={"algorithm": "greedy_modularity", "max_topics": max_topics},
            )
        )
    return output


def _tfidf_clusters(publications: list[ParsedPublication], max_topics: int) -> list[TopicCluster]:
    documents = [f"{item.title} {item.abstract_text or ''}" for item in publications]
    usable = [(publication, document) for publication, document in zip(publications, documents, strict=True) if len(document) >= 30]
    if len(usable) < 3:
        return []
    count = min(max_topics, max(2, int(math.sqrt(len(usable) / 2))))
    vectorizer = TfidfVectorizer(stop_words="english", max_features=1500, min_df=1, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform([document for _, document in usable])
    if matrix.shape[1] < count:
        return []
    model = KMeans(n_clusters=count, random_state=42, n_init=10)
    labels = model.fit_predict(matrix)
    terms = vectorizer.get_feature_names_out()
    output: list[TopicCluster] = []
    for topic_index in range(count):
        members = [usable[index][0].pmid for index, label in enumerate(labels) if label == topic_index]
        top_indices = model.cluster_centers_[topic_index].argsort()[::-1][:8]
        output.append(
            TopicCluster(
                index=topic_index + 1,
                terms=tuple(str(terms[index]) for index in top_indices),
                pmids=tuple(sorted(members)),
                method="tfidf_kmeans",
                confidence=None,
                parameters={"random_state": 42, "clusters": count},
            )
        )
    return sorted(output, key=lambda cluster: (-len(cluster.pmids), cluster.index))


def cluster_topics(publications: list[ParsedPublication], max_topics: int = 8) -> list[TopicCluster]:
    mesh_coverage = sum(bool(item.mesh_terms) for item in publications) / max(len(publications), 1)
    if mesh_coverage >= 0.35:
        clusters = _mesh_clusters(publications, max_topics)
        if clusters:
            return clusters
    return _tfidf_clusters(publications, max_topics)

