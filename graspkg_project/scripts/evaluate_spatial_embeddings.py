"""Leave-one-out link-prediction evaluation for the ComplEx refinement
layer: for each observed (subject class, relation, object class) fact,
hide it, retrain on the rest, and check whether the model still ranks the
true tail highly. This is the evidence for the one-pager's "predict a
Table exists under a Plate" claim - entities are fixed from the *full*
triple set (standard transductive protocol) so hiding a fact never
orphans an entity that has no other edges left.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spatialkg.embeddings import ComplEx, triples_from_store
from spatialkg.scene_loader import load_scene_file
from spatialkg.store import SpatialStore

SAMPLE_SCENE = Path(__file__).resolve().parent.parent / "spatialkg" / "sample_data" / "sample_scene.json"


def main(epochs=200, dim=16):
    store = SpatialStore()
    store.load_default_ontology()
    load_scene_file(store, SAMPLE_SCENE)
    all_triples = triples_from_store(store)
    all_entities = sorted({t.head for t in all_triples} | {t.tail for t in all_triples})
    all_relations = sorted({t.relation for t in all_triples})

    print(f"{len(all_triples)} class-level facts over {len(all_entities)} entities, {len(all_relations)} relations")
    print(f"{'head':<16}{'relation':<14}{'true tail':<14}{'rank':>6}")

    ranks = []
    for held_out in all_triples:
        train_triples = [t for t in all_triples if t != held_out]
        model = ComplEx(train_triples, dim=dim, seed=0, entities=all_entities, relations=all_relations)
        model.fit(epochs=epochs, lr=0.05)
        rank = model.rank_of(held_out.head, held_out.relation, held_out.tail)
        ranks.append(rank)
        print(f"{held_out.head:<16}{held_out.relation:<14}{held_out.tail:<14}{rank:>6}")

    n = len(ranks)
    mean_rank = sum(ranks) / n
    hits_at_3 = sum(1 for r in ranks if r <= 3) / n
    print(f"\nmean rank: {mean_rank:.2f}   hits@3: {hits_at_3:.0%}   (n={n} held-out facts, {len(all_entities)} candidate entities)")


if __name__ == "__main__":
    main()
