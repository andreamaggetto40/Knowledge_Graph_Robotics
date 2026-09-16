"""Refinement via embeddings: a minimal TransE implementation used to predict
likely affordances / grasp types for object categories whose relations are
missing or hidden - i.e. to generalise past PODGE's 12 hard-coded classes.

Deliberately implemented from scratch with numpy only (no PyKEEN/DGL-KE) so
the mechanics stay fully inspectable for the course write-up. Swap in a
library for production use once you outgrow this.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Triple:
    head: str
    relation: str
    tail: str


class TransE:
    """h + r ~= t, trained with margin ranking loss and random negative
    sampling (corrupting head or tail)."""

    def __init__(self, triples, dim: int = 24, seed: int = 0, entities=None, relations=None):
        """`entities`/`relations` let a caller fix the full vocabulary up
        front (the standard transductive link-prediction protocol: the set
        of entities is known, only some *facts* about them are hidden for
        testing). If omitted, the vocabulary is derived from `triples`
        directly, which is what you want for normal training/inference -
        see evaluate_embeddings.py for why the fixed-vocabulary form
        matters for leave-one-out evaluation."""
        self.triples = list(triples)
        self.dim = dim
        self._rng = np.random.default_rng(seed)

        self.entities = sorted(entities) if entities is not None else sorted(
            {t.head for t in self.triples} | {t.tail for t in self.triples}
        )
        self.relations = sorted(relations) if relations is not None else sorted(
            {t.relation for t in self.triples}
        )
        self.ent_idx = {e: i for i, e in enumerate(self.entities)}
        self.rel_idx = {r: i for i, r in enumerate(self.relations)}

        bound = 6 / math.sqrt(dim)
        self.E = self._rng.uniform(-bound, bound, size=(len(self.entities), dim))
        self.R = self._rng.uniform(-bound, bound, size=(len(self.relations), dim))
        self._normalize_entities()

    def _normalize_entities(self):
        norms = np.linalg.norm(self.E, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.E /= norms

    def _score(self, h, r, t) -> float:
        return float(np.sum((self.E[h] + self.R[r] - self.E[t]) ** 2))

    def fit(self, epochs: int = 300, lr: float = 0.02, margin: float = 1.0):
        idx_triples = [
            (self.ent_idx[t.head], self.rel_idx[t.relation], self.ent_idx[t.tail]) for t in self.triples
        ]
        n_ent = len(self.entities)
        for _ in range(epochs):
            idx_triples = [idx_triples[i] for i in self._rng.permutation(len(idx_triples))]
            for h, r, t in idx_triples:
                corrupt_head = self._rng.random() < 0.5
                h_neg, t_neg = h, t
                if corrupt_head:
                    h_neg = int(self._rng.integers(0, n_ent))
                else:
                    t_neg = int(self._rng.integers(0, n_ent))

                diff_pos = self.E[h] + self.R[r] - self.E[t]
                diff_neg = self.E[h_neg] + self.R[r] - self.E[t_neg]
                pos_dist = float(np.sum(diff_pos**2))
                neg_dist = float(np.sum(diff_neg**2))
                loss = margin + pos_dist - neg_dist
                if loss <= 0:
                    continue

                grad_pos = 2 * diff_pos
                grad_neg = 2 * diff_neg
                self.E[h] -= lr * grad_pos
                self.R[r] -= lr * (grad_pos - grad_neg)
                self.E[t] += lr * grad_pos
                if corrupt_head:
                    self.E[h_neg] += lr * grad_neg
                else:
                    self.E[t_neg] -= lr * grad_neg
            self._normalize_entities()

    def predict_tail(self, head: str, relation: str, k: int = 3, exclude_known: bool = True):
        """Ranks all entities as candidate tails for (head, relation, ?)."""
        h, r = self.ent_idx[head], self.rel_idx[relation]
        known = {t.tail for t in self.triples if t.head == head and t.relation == relation}
        scored = []
        for e in self.entities:
            if exclude_known and e in known:
                continue
            scored.append((e, self._score(h, r, self.ent_idx[e])))
        scored.sort(key=lambda x: x[1])
        return scored[:k]

    def rank_of(self, head: str, relation: str, true_tail: str) -> int:
        """1-based rank of true_tail among all entities scored as tail candidates."""
        h, r = self.ent_idx[head], self.rel_idx[relation]
        scored = sorted(self.entities, key=lambda e: self._score(h, r, self.ent_idx[e]))
        return scored.index(true_tail) + 1


def triples_from_store(store, relations=("hasAffordance", "recommendedGraspType")):
    """Pulls the category-level background knowledge (not per-instance
    derived facts) out of the store as training triples for TransE."""
    values_clause = " ".join(f"grasp:{r}" for r in relations)
    query = f"""
    PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
    SELECT ?cat ?rel ?val WHERE {{
        VALUES ?rel {{ {values_clause} }}
        ?cat ?rel ?val .
        FILTER(STRSTARTS(STR(?cat), STR(grasp:)))
    }}
    """
    triples = []
    for row in store.select(query):
        head = str(row.cat).rsplit("#", 1)[-1]
        rel = str(row.rel).rsplit("#", 1)[-1]
        tail = str(row.val).rsplit("#", 1)[-1]
        triples.append(Triple(head, rel, tail))
    return triples
