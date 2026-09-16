"""KG store: a thin wrapper around rdflib.Graph with the helpers GraspKG
needs (loading the ontology, minting instance URIs, running SPARQL)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Namespace, URIRef

GRASP = Namespace("http://v4r.tuwien.ac.at/graspkg#")

_DEFAULT_ONTOLOGY = Path(__file__).resolve().parent / "ontology" / "grasp_ontology.ttl"


class GraspStore:
    """Owns the working RDF graph for one GraspKG session."""

    def __init__(self):
        self.graph = Graph()
        self.graph.bind("grasp", GRASP)

    def load_ontology(self, path) -> None:
        self.graph.parse(str(path), format="turtle")

    def load_default_ontology(self) -> None:
        self.load_ontology(_DEFAULT_ONTOLOGY)

    def new_instance_uri(self, prefix: str = "obj") -> URIRef:
        return GRASP[f"{prefix}_{uuid.uuid4().hex[:10]}"]

    def add(self, triples: Iterable[tuple]) -> None:
        for s, p, o in triples:
            self.graph.add((s, p, o))

    def select(self, query: str):
        """Runs a SPARQL SELECT and returns the rows."""
        return list(self.graph.query(query))

    def construct(self, query: str) -> int:
        """Runs a SPARQL CONSTRUCT rule and merges only the *new* triples
        into the working graph. Returns how many triples were actually
        added (0 once the rule has reached its fixpoint)."""
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
