"""Sanity-checks the rule layer: run many simulated detections through the
full graph-creation + reasoning pipeline and report rule coverage and the
consistency-check trigger rate.

This validates the *pipeline's plumbing*, not real grasp success - swap
SimulatedPODGEStream for a PODGEAdapter reading logged real detections
once you have them, and re-run the same checks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graspkg import reasoning
from graspkg.detectors import SimulatedPODGEStream
from graspkg.graph_creation import add_detections
from graspkg.store import GraspStore


def main(n=300, seed=1):
    store = GraspStore()
    store.load_default_ontology()
    reasoning.materialize_rdfs(store)

    stream = SimulatedPODGEStream(seed=seed)
    detections = stream.sample(n)
    add_detections(store, detections)

    reasoning.materialize_rdfs(store)  # new instances also need their type closure
    reasoning.run_rules(store)
    n_flagged = reasoning.check_pose_consistency(store)

    rows = store.select(
        """
        PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
        SELECT (COUNT(?o) AS ?total) (COUNT(?gt) AS ?withGrasp) WHERE {
            ?o a grasp:DetectedObject .
            OPTIONAL { ?o grasp:derivedGraspType ?gt }
        }
        """
    )
    total, with_grasp = int(rows[0].total), int(rows[0].withGrasp)
    print(f"detections: {total}")
    print(f"rule coverage (derivedGraspType asserted): {with_grasp}/{total} ({with_grasp / total:.0%})")
    print(f"flagged for pose inconsistency: {n_flagged}/{total} ({n_flagged / total:.0%})")


if __name__ == "__main__":
    main()
