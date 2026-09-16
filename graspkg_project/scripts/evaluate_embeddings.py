"""Leave-one-out link-prediction evaluation for the TransE refinement layer.

For each category-level triple, hide it, retrain on the rest, and check
whether the model still ranks the true tail highly among all candidates.
The entity/relation vocabulary is fixed from the *full* triple set (the
standard transductive protocol) so a hidden fact never orphans an entity
that has no other edges left.

Two relations are evaluated, deliberately, because they behave very
differently in this small ontology:

- hasAffordance is shared across categories (several categories point at
  the same affordance, e.g. "Graspable"), so there is real structure for
  the embedding to learn from - ranks should be good.
- recommendedGraspType is currently a clean one-to-one mapping (each
  category has exactly one grasp type), so hiding it leaves the model with
  no signal at all about that specific edge - ranks are expected to be
  close to random. That is not a bug; it is a useful, honest finding for
  the course write-up: embeddings help when there is redundant structure to
  generalise from, and this ontology will need more objects/relations
  before that relation benefits from them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graspkg.embeddings import TransE, triples_from_store
from graspkg.store import GraspStore


def leave_one_out(all_triples, relation, epochs=200, dim=16):
    all_entities = sorted({t.head for t in all_triples} | {t.tail for t in all_triples})
    all_relations = sorted({t.relation for t in all_triples})

    held_out_triples = [t for t in all_triples if t.relation == relation]
    ranks = []
    print(f"\n[{relation}]")
    print(f"{'head':<22}{'true tail':<24}{'rank':>6}   (out of {len(all_entities)} entities)")
    for held_out in held_out_triples:
        train_triples = [t for t in all_triples if t != held_out]
        model = TransE(train_triples, dim=dim, seed=0, entities=all_entities, relations=all_relations)
        model.fit(epochs=epochs, lr=0.05)
        rank = model.rank_of(held_out.head, relation, held_out.tail)
        ranks.append(rank)
        print(f"{held_out.head:<22}{held_out.tail:<24}{rank:>6}")

    n = len(ranks)
    mean_rank = sum(ranks) / n
    hits_at_3 = sum(1 for r in ranks if r <= 3) / n
    print(f"mean rank: {mean_rank:.2f}   hits@3: {hits_at_3:.0%}   (n={n} held-out facts)")


def main():
    store = GraspStore()
    store.load_default_ontology()
    all_triples = triples_from_store(store)

    leave_one_out(all_triples, "hasAffordance")
    leave_one_out(all_triples, "recommendedGraspType")


if __name__ == "__main__":
    main()
