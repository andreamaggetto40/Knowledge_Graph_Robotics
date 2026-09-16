"""Sanity-checks the recursive rule layer on the sample scene: how much of
the KG's room membership is *derived* rather than directly observed, and
how large the reachability closure is. Swap in a real 3RScan/3DSSG-loaded
scene (same scene_loader.load_scene_file call) once you have licensed
access, and re-run these same checks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spatialkg import reasoning
from spatialkg.scene_loader import load_scene_file
from spatialkg.store import SpatialStore

SAMPLE_SCENE = Path(__file__).resolve().parent.parent / "spatialkg" / "sample_data" / "sample_scene.json"


def main():
    store = SpatialStore()
    store.load_default_ontology()
    load_scene_file(store, SAMPLE_SCENE)
    reasoning.materialize_rdfs(store)

    before = len(store)
    added = reasoning.run_rules(store)
    after = len(store)
    print(f"triples before rules: {before}, after: {after} (+{added})")

    rows = store.select(
        """
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT (COUNT(DISTINCT ?obj) AS ?total) WHERE { ?obj sp:locatedIn ?r }
        """
    )
    total_located = int(rows[0].total)

    direct_rows = store.select(
        """
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT (COUNT(DISTINCT ?obj) AS ?n) WHERE {
            ?obj sp:locatedIn ?r .
            FILTER NOT EXISTS { ?obj (sp:supportedBy|sp:insideOf|sp:hangingOn|sp:attachedTo)+ ?anchor }
        }
        """
    )
    direct = int(direct_rows[0].n)
    print(f"entities located: {total_located} ({direct} furniture/direct, {total_located - direct} via recursive propagation)")

    reach_rows = store.select(
        "PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#> SELECT (COUNT(*) AS ?n) WHERE { ?r1 sp:reachableFrom ?r2 }"
    )
    n_rooms = len(store.select("PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#> SELECT ?r WHERE { ?r a sp:Room }"))
    print(f"reachability pairs derived: {int(reach_rows[0].n)} (out of {n_rooms * (n_rooms - 1)} possible ordered pairs among {n_rooms} rooms)")


if __name__ == "__main__":
    main()
