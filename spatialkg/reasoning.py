"""(l, r) - the deductive layer: RDFS class-hierarchy entailment plus two
*recursive* rules expressed as SPARQL property paths - this is the native
way to get "recursive rules for spatial hierarchies and containment" and
for reachability without a dedicated Datalog+/- engine (see
../vadalog_reference/ for the same two rules written in Vadalog's own
syntax, since real Vadalog access is gated - see the chat history).
"""
from __future__ import annotations

from datetime import datetime, timezone

import owlrl
from rdflib import Literal
from rdflib.namespace import XSD

from .reference_data import DEFAULT_STALENESS_THRESHOLD_SECONDS
from .store import SP, SpatialStore

# Any chain of these counts as "still effectively in the same room" - e.g.
# mug supportedBy table, table locatedIn Kitchen => mug locatedIn Kitchen,
# and the '+' makes this apply through arbitrarily long support chains
# (book on tray on table), not just one hop. This is the recursive part.
_CONTAINMENT_PATH = "(sp:supportedBy|sp:insideOf|sp:hangingOn|sp:attachedTo)+"

RULE_PROPAGATE_ROOM = f"""
PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
CONSTRUCT {{ ?obj sp:locatedIn ?room }}
WHERE {{
    ?obj {_CONTAINMENT_PATH} ?anchor .
    ?anchor sp:locatedIn ?room .
    FILTER NOT EXISTS {{ ?obj sp:locatedIn ?room }}
}}
"""

RULE_REACHABLE_ROOMS = """
PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
CONSTRUCT { ?r1 sp:reachableFrom ?r2 }
WHERE {
    ?r1 sp:adjacentRoom+ ?r2 .
    FILTER (?r1 != ?r2)
    FILTER NOT EXISTS { ?r1 sp:reachableFrom ?r2 }
}
"""

RULES = [RULE_PROPAGATE_ROOM, RULE_REACHABLE_ROOMS]


def materialize_rdfs(store: SpatialStore) -> None:
    """RDFS subclass entailment (e.g. a Mug individual also becomes
    rdf:type PortableObject). Mutates store.graph in place."""
    owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(store.graph)


def run_rules(store: SpatialStore, max_iterations: int = 10) -> int:
    """Naive forward-chaining fixpoint over RULES. Returns total new triples."""
    total_added = 0
    for _ in range(max_iterations):
        added_this_round = sum(store.construct(rule) for rule in RULES)
        total_added += added_this_round
        if added_this_round == 0:
            break
    return total_added


def check_staleness(store: SpatialStore, threshold_seconds: int = DEFAULT_STALENESS_THRESHOLD_SECONDS, now=None) -> int:
    """Flags every entity whose most recent observedAt is older than the
    threshold as sp:isStale - so the query service can be honest about
    "last confirmed 6 hours ago" instead of asserting a stale fact as
    current truth. Returns the number of entities flagged."""
    now = now or datetime.now(tz=timezone.utc)
    rows = store.select(
        """
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT ?obj (MAX(?t) AS ?latest) WHERE {
            ?obj sp:observedAt ?t .
        } GROUP BY ?obj
        """
    )
    flagged = 0
    for row in rows:
        latest = datetime.fromisoformat(str(row.latest))
        age = (now - latest).total_seconds()
        is_stale = age > threshold_seconds
        store.graph.remove((row.obj, SP.isStale, None))
        store.add([(row.obj, SP.isStale, Literal(is_stale, datatype=XSD.boolean))])
        flagged += int(is_stale)
    return flagged
