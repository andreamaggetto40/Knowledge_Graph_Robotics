"""Refinement via embeddings: ComplEx (Trouillon et al. 2016), implemented
from scratch with numpy - chosen over TransE specifically because
supportedBy/insideOf are asymmetric (a table is not supportedBy a plate),
and ComplEx's complex-valued bilinear score handles that naturally where
TransE's translation distance does not. Used for exactly the one-pager's
example: given a visible "Plate", predict the occluded "Table" underneath
it, by link-predicting the tail of (PlateClass, supportedBy, ?).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Triple:
    head: str
    relation: str
    tail: str


class ComplEx:
    """Each entity/relation gets a real part and an imaginary part
    (dim floats each). score(h,r,t) = Re(sum_k h_k * r_k * conj(t_k)),
    trained with logistic loss and random negative sampling."""

    def __init__(self, triples, dim: int = 24, seed: int = 0, entities=None, relations=None, reg: float = 0.001):
        self.triples = list(triples)
        self.dim = dim
        self.reg = reg
        self._rng = np.random.default_rng(seed)

        self.entities = sorted(entities) if entities is not None else sorted(
            {t.head for t in self.triples} | {t.tail for t in self.triples}
        )
        self.relations = sorted(relations) if relations is not None else sorted({t.relation for t in self.triples})
        self.ent_idx = {e: i for i, e in enumerate(self.entities)}
        self.rel_idx = {r: i for i, r in enumerate(self.relations)}

        n_e, n_r = len(self.entities), len(self.relations)
        scale = 1.0 / np.sqrt(dim)
        self.E_re = self._rng.normal(0, scale, size=(n_e, dim))
        self.E_im = self._rng.normal(0, scale, size=(n_e, dim))
        self.R_re = self._rng.normal(0, scale, size=(n_r, dim))
        self.R_im = self._rng.normal(0, scale, size=(n_r, dim))

    def _score_vec(self, h, r, t) -> float:
        hr, hi = self.E_re[h], self.E_im[h]
        rr, ri = self.R_re[r], self.R_im[r]
        tr, ti = self.E_re[t], self.E_im[t]
        return float(np.sum(hr * rr * tr + hr * ri * ti + hi * rr * ti - hi * ri * tr))

    @staticmethod
    def _sigmoid(x):
        return 1.0 / (1.0 + np.exp(-x))

    def _step(self, h, r, t, target, lr):
        hr, hi = self.E_re[h], self.E_im[h]
        rr, ri = self.R_re[r], self.R_im[r]
        tr, ti = self.E_re[t], self.E_im[t]

        score = float(np.sum(hr * rr * tr + hr * ri * ti + hi * rr * ti - hi * ri * tr))
        grad_s = self._sigmoid(score) - target  # d(loss)/d(score)

        d_hr = rr * tr + ri * ti
        d_hi = rr * ti - ri * tr
        d_rr = hr * tr + hi * ti
        d_ri = hr * ti - hi * tr
        d_tr = hr * rr - hi * ri
        d_ti = hr * ri + hi * rr

        self.E_re[h] -= lr * (grad_s * d_hr + self.reg * hr)
        self.E_im[h] -= lr * (grad_s * d_hi + self.reg * hi)
        self.R_re[r] -= lr * (grad_s * d_rr + self.reg * rr)
        self.R_im[r] -= lr * (grad_s * d_ri + self.reg * ri)
        self.E_re[t] -= lr * (grad_s * d_tr + self.reg * tr)
        self.E_im[t] -= lr * (grad_s * d_ti + self.reg * ti)

    def fit(self, epochs: int = 300, lr: float = 0.05, neg_per_pos: int = 2):
        idx_triples = [(self.ent_idx[t.head], self.rel_idx[t.relation], self.ent_idx[t.tail]) for t in self.triples]
        n_ent = len(self.entities)
        for _ in range(epochs):
            idx_triples = [idx_triples[i] for i in self._rng.permutation(len(idx_triples))]
            for h, r, t in idx_triples:
                self._step(h, r, t, target=1.0, lr=lr)
                for _ in range(neg_per_pos):
                    if self._rng.random() < 0.5:
                        self._step(int(self._rng.integers(0, n_ent)), r, t, target=0.0, lr=lr)
                    else:
                        self._step(h, r, int(self._rng.integers(0, n_ent)), target=0.0, lr=lr)

    def predict_tail(self, head: str, relation: str, k: int = 3, exclude_known: bool = True):
        h, r = self.ent_idx[head], self.rel_idx[relation]
        known = {t.tail for t in self.triples if t.head == head and t.relation == relation}
        scored = []
        for e in self.entities:
            if exclude_known and e in known:
                continue
            scored.append((e, self._score_vec(h, r, self.ent_idx[e])))
        scored.sort(key=lambda x: -x[1])  # higher score = more plausible for ComplEx
        return scored[:k]

    def rank_of(self, head: str, relation: str, true_tail: str) -> int:
        h, r = self.ent_idx[head], self.rel_idx[relation]
        scored = sorted(self.entities, key=lambda e: -self._score_vec(h, r, self.ent_idx[e]))
        return scored.index(true_tail) + 1


def triples_from_store(store, relations=("supportedBy", "insideOf", "hangingOn", "attachedTo")):
    """Pulls observed (subject leafClass, relation, object leafClass)
    patterns out of the store - class-level, deduplicated, so the model
    learns "mugs tend to be on tables" rather than memorising one instance."""
    query = """
    PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
    SELECT DISTINCT ?relName ?subjClass ?objClass WHERE {
        VALUES (?rel ?relName) {
            (sp:supportedBy "supportedBy") (sp:insideOf "insideOf")
            (sp:hangingOn "hangingOn") (sp:attachedTo "attachedTo")
        }
        ?subj ?rel ?obj .
        ?subj sp:leafClass ?subjClass .
        ?obj sp:leafClass ?objClass .
    }
    """
    triples = []
    for row in store.select(query):
        if str(row.relName) not in relations:
            continue
        triples.append(Triple(str(row.subjClass), str(row.relName), str(row.objClass)))
    return triples
