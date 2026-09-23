"""
Module: knowledge_graph.py
Description: Lightweight concept graph for Engine 01, built incrementally
    as chunks are ingested. Nodes: documents, authors, topics. Edges:
    document-BY-author, document-HAS_TOPIC-topic (weighted by chunk
    count), topic-CO_OCCURS_WITH-topic (weighted by co-occurrence within
    the same chunk). Backs related_topics()/get_sources().
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import networkx as nx

from project_titan_x.engines.e01_knowledge.models import Chunk

_DOC = "document"
_AUTHOR = "author"
_TOPIC = "topic"


class KnowledgeGraph:
    def __init__(self) -> None:
        self._graph = nx.Graph()

    def add_chunk(self, chunk: Chunk) -> None:
        doc_node = (_DOC, chunk.doc_id)
        author_node = (_AUTHOR, chunk.author)
        self._graph.add_node(doc_node, kind=_DOC, title=chunk.title, source=chunk.source)
        self._graph.add_node(author_node, kind=_AUTHOR)
        self._graph.add_edge(doc_node, author_node, relation="written_by")

        topic_nodes = [(_TOPIC, t.value) for t in chunk.topics]
        for topic_node in topic_nodes:
            self._graph.add_node(topic_node, kind=_TOPIC)
            self._bump_edge(doc_node, topic_node, relation="has_topic")

        for i in range(len(topic_nodes)):
            for j in range(i + 1, len(topic_nodes)):
                self._bump_edge(topic_nodes[i], topic_nodes[j], relation="co_occurs")

    def _bump_edge(self, a: tuple[str, str], b: tuple[str, str], relation: str) -> None:
        if self._graph.has_edge(a, b):
            self._graph[a][b]["weight"] += 1
        else:
            self._graph.add_edge(a, b, relation=relation, weight=1)

    def related_topics(self, topic: str, limit: int = 5) -> list[tuple[str, int]]:
        """Topics that most frequently co-occur with `topic` in the same chunk."""
        node = (_TOPIC, topic)
        if node not in self._graph:
            return []
        neighbors = [
            (n[1], self._graph[node][n].get("weight", 1))
            for n in self._graph.neighbors(node)
            if n[0] == _TOPIC
        ]
        neighbors.sort(key=lambda pair: pair[1], reverse=True)
        return neighbors[:limit]

    def sources_for_topic(self, topic: str) -> list[str]:
        """Document titles that contain at least one chunk tagged with `topic`."""
        node = (_TOPIC, topic)
        if node not in self._graph:
            return []
        return [
            self._graph.nodes[n].get("title", n[1])
            for n in self._graph.neighbors(node)
            if n[0] == _DOC
        ]

    def topics_for_author(self, author: str) -> list[str]:
        node = (_AUTHOR, author)
        if node not in self._graph:
            return []
        docs = [n for n in self._graph.neighbors(node) if n[0] == _DOC]
        topics: set[str] = set()
        for doc_node in docs:
            topics.update(n[1] for n in self._graph.neighbors(doc_node) if n[0] == _TOPIC)
        return sorted(topics)

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()
