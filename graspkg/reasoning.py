"""(l, r) - the deductive layer: RDFS class-hierarchy entailment, a small set
of forward-chaining SPARQL rules, and a procedural pose-consistency check."""
from __future__ import annotations

import math

import owlrl
from rdflib import Literal
from rdflib.namespace import XSD

from .reference_data import STABLE_ORIENTATIONS_BY_CATEGORY
from .store import GRASP, GraspStore

# --- SPARQL CONSTRUCT rules -------------------------------------------------
# Each rule reads the graph (post RDFS-closure, so instances carry every
# ancestor category as an rdf:type) and derives new, instance-level facts.

RULE_DERIVE_GRASP_TYPE = """
PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
CONSTRUCT { ?obj grasp:derivedGraspType ?gt }
WHERE {
    ?obj a grasp:DetectedObject ;
         a ?cat .
    ?cat grasp:recommendedGraspType ?gt .
}
"""

RULE_PROPAGATE_AFFORDANCE = """
PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
CONSTRUCT { ?obj grasp:hasAffordance ?aff }
WHERE {
    ?obj a grasp:DetectedObject ;
         a ?cat .
    ?cat grasp:hasAffordance ?aff .
}
"""

RULES = [RULE_DERIVE_GRASP_TYPE, RULE_PROPAGATE_AFFORDANCE]


def materialize_rdfs(store: GraspStore) -> None:
    """RDFS subclass entailment, so e.g. a Mug individual also becomes
    rdf:type HandleGraspable. Mutates store.graph in place."""
    owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(store.graph)


def run_rules(store: GraspStore, max_iterations: int = 10) -> int:
    """Naive forward-chaining fixpoint over RULES. Returns total new triples."""
    total_added = 0
    for _ in range(max_iterations):
        added_this_round = sum(store.construct(rule) for rule in RULES)
        total_added += added_this_round
        if added_this_round == 0:
            break
    return total_added


# --- Procedural consistency check ------------------------------------------
# Uses STABLE_ORIENTATIONS_BY_CATEGORY from reference_data.py (shared with
# the simulator, so both agree on what "stable" means for each category).
_ANGLE_TOLERANCE_DEG = 40.0


def _quat_angle_deg(q1, q2) -> float:
    """Angle in degrees between two unit quaternions (shortest rotation)."""
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(q1, q2))))
    return math.degrees(2 * math.acos(abs(dot)))


def check_pose_consistency(store: GraspStore) -> int:
    """Flags each grasp:DetectedObject whose pose doesn't match any known
    stable orientation for its (RDFS-inferred) top-level category. Returns
    the number of instances flagged in this call."""
    query = """
    PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
    SELECT ?obj ?cat ?qx ?qy ?qz ?qw WHERE {
        ?obj a grasp:DetectedObject ; a ?cat .
        ?obj grasp:quatX ?qx ; grasp:quatY ?qy ; grasp:quatZ ?qz ; grasp:quatW ?qw .
        FILTER(STRSTARTS(STR(?cat), STR(grasp:)))
    }
    """
    flagged = set()
    for row in store.select(query):
        cat_name = str(row.cat).rsplit("#", 1)[-1]
        refs = STABLE_ORIENTATIONS_BY_CATEGORY.get(cat_name)
        if refs is None or row.obj in flagged:
            continue
        pose = (float(row.qx), float(row.qy), float(row.qz), float(row.qw))
        min_angle = min(_quat_angle_deg(pose, ref) for ref in refs)
        if min_angle > _ANGLE_TOLERANCE_DEG:
            store.add([(row.obj, GRASP.hasConsistencyIssue, Literal(True, datatype=XSD.boolean))])
            flagged.add(row.obj)
    return len(flagged)
