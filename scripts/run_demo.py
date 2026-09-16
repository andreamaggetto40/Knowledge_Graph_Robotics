"""End-to-end GraspKG demo: perception -> graph creation -> reasoning ->
advisory service -> feedback, all running on simulated PODGE detections.
No ROS, no GPU, no robot required.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graspkg import feedback, reasoning
from graspkg.advisory_service import GraspAdvisoryService
from graspkg.detectors import SimulatedPODGEStream
from graspkg.embeddings import TransE, triples_from_store
from graspkg.graph_creation import add_detections
from graspkg.store import GraspStore


def main():
    # 1. graph creation (g): load the TBox, materialise RDFS, ingest detections
    store = GraspStore()
    store.load_default_ontology()
    reasoning.materialize_rdfs(store)

    stream = SimulatedPODGEStream(seed=42, unstable_pose_rate=0.2)
    detections = stream.sample(8)
    instances = add_detections(store, detections)
    reasoning.materialize_rdfs(store)

    # 2. deductive reasoning (l, r)
    added = reasoning.run_rules(store)
    flagged = reasoning.check_pose_consistency(store)
    print(f"[reasoning] derived {added} new triples, flagged {flagged} inconsistent poses\n")

    # 3. refinement via embeddings (r): train once on the category-level KG
    triples = triples_from_store(store)
    embed_model = TransE(triples, dim=16, seed=0)
    embed_model.fit(epochs=200, lr=0.05)

    # 4. advisory service (LO11): explain a grasp decision for every detection
    service = GraspAdvisoryService(store, embedding_model=embed_model)
    print("[advisory service]")
    for inst in instances:
        advice = service.advise(inst)
        print("  " + service.explain(advice))

    # 5. feedback loop (LO8): pretend three of the grasps were attempted
    print("\n[feedback]")
    for inst in instances[:3]:
        advice = service.advise(inst)
        if advice.grasp_type is None:
            continue
        success = advice.consistency_ok  # toy rule: inconsistent poses fail more often
        _, rate = feedback.record_outcome(store, inst, advice.category, advice.grasp_type, success)
        print(f"  logged attempt on {advice.category}: success={success} -> running rate {rate:.0%}")

    print(f"\n[store] graph now holds {len(store)} triples")


if __name__ == "__main__":
    main()
