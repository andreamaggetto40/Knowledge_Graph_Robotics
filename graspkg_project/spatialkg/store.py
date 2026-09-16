"""KG store: a thin wrapper around rdflib.Graph, same pattern as
graspkg/store.py (deliberately - the two KGs share an engineering pattern
even though their ontologies differ)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Namespace, URIRef

SP = Namespace("http://v4r.tuwien.ac.at/spatialkg#")

_DEFAULT_ONTOLOGY = Path(__file__).resolve().parent / "ontology" / "spatial_ontology.ttl"


class SpatialStore:
    """Owns the working RDF graph for one SpatialKG session."""

    def __init__(self):
        self.graph = Graph()
        self.graph.bind("sp", SP)

    def load_ontology(self, path) -> None:
        self.graph.parse(str(path), format="turtle")

    def load_default_ontology(self) -> None:
        self.load_ontology(_DEFAULT_ONTOLOGY)

    def new_instance_uri(self, prefix: str = "obs") -> URIRef:
        return SP[f"{prefix}_{uuid.uuid4().hex[:10]}"]

    def add(self, triples: Iterable[tuple]) -> None:
        for s, p, o in triples:
            self.graph.add((s, p, o))

    def select(self, query: str):
        return list(self.graph.query(query))

    def construct(self, query: str) -> int:
        """Runs a SPARQL CONSTRUCT rule, merges only the new triples in,
        and returns how many were actually added (0 at fixpoint)."""
        result_graph = self.graph.query(query).graph
        added = 0
        for triple in result_graph:
            if triple not in self.graph:
                self.graph.add(triple)
                added += 1
        return added

    def serialize(self, path, fmt: str = "turtle") -> None:
        self.graph.serialize(destination=str(path), format=fmt)

    def __len__(self):
        return len(self.graph)
