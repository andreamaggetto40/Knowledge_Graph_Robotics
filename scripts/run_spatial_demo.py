"""End-to-end SpatialKG demo: knowledge acquisition from a 3DSSG-format
sample scene -> recursive spatial/reachability rules -> ComplEx-based
occlusion prediction -> the query service an LLM would call -> a
human correction closing the loop (LO8). No ROS, no robot, no licensed
3RScan download required.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spatialkg import evolution, reasoning
from spatialkg.embeddings import ComplEx, triples_from_store
from spatialkg.query_service import SpatialQueryService
from spatialkg.scene_loader import load_scene_file
from spatialkg.store import SpatialStore

SAMPLE_SCENE = Path(__file__).resolve().parent.parent / "spatialkg" / "sample_data" / "sample_scene.json"


def main():
    # 1. knowledge acquisition (g)
    store = SpatialStore()
    store.load_default_ontology()
    report = load_scene_file(store, SAMPLE_SCENE)
    print(f"[acquisition] loaded {report['scans']} scans, {report['objects']} object observations, "
          f"{report['relationships']} relationships, {report['same_instance_links']} same-instance links\n")

    # 2. deductive reasoning (l, r) - recursive room propagation + reachability
    reasoning.materialize_rdfs(store)
    added = reasoning.run_rules(store)
    flagged = reasoning.check_staleness(store, now=datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc))
    print(f"[reasoning] derived {added} new triples via recursive rules, {flagged} entities stale (as of 15:30 on scan day)\n")

    can_reach = store.select("""
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT ?r2 WHERE { sp:Kitchen sp:reachableFrom ?r2 }
    """)
    print("[reachability] rooms reachable from Kitchen:", [str(r.r2).rsplit('#', 1)[-1] for r in can_reach], "\n")

    # 3. refinement via embeddings (r) - ComplEx on the class-level support graph
    triples = triples_from_store(store)
    model = ComplEx(triples, dim=16, seed=0)
    model.fit(epochs=200, lr=0.05)

    # 4. the query service (System of Record) - what sasha_gpt would call
    service = SpatialQueryService(store, embedding_model=model)
    print("[query service]")
    for query_class in ["Mug", "FoamBrick", "PowerDrill"]:
        answer = service.locate(query_class)
        print("  " + service.explain(answer))

    # 5. KG evolution (LO8) - a correction closes the loop
    print("\n[evolution] applying a correction: MustardBottle moved to LivingRoom")
    evolution.apply_correction(store, "MustardBottle", "LivingRoom", corrected_by="user")
    reasoning.run_rules(store)
    answer = service.locate("MustardBottle")
    print("  " + service.explain(answer))

    print(f"\n[store] graph now holds {len(store)} triples")


if __name__ == "__main__":
    main()
