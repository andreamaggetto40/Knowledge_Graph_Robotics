"""(LO11) A small grasp-advisory 'service' on top of GraspKG: given a
detected-object instance, answer 'how should I grasp this, and why', falling
back to the embedding model when no rule fired (e.g. an unseen category)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import feedback
from .store import GraspStore


@dataclass
class GraspAdvice:
    instance: str
    category: str
    grasp_type: Optional[str]
    confidence: float
    consistency_ok: bool
    source: str  # "rule" | "embedding" | "none"
    known_success_rate: Optional[float]


class GraspAdvisoryService:
    def __init__(self, store: GraspStore, embedding_model=None):
        self.store = store
        self.embedding_model = embedding_model

    def advise(self, instance_uri) -> GraspAdvice:
        rows = self.store.select(
            f"""
            PREFIX grasp: <http://v4r.tuwien.ac.at/graspkg#>
            SELECT ?leaf ?conf ?issue ?gt WHERE {{
                <{instance_uri}> grasp:leafClass ?leaf ; grasp:hasConfidence ?conf .
                OPTIONAL {{ <{instance_uri}> grasp:hasConsistencyIssue ?issue }}
                OPTIONAL {{ <{instance_uri}> grasp:derivedGraspType ?gt }}
            }}
            """
        )
        if not rows:
            raise ValueError(f"no detection found for {instance_uri}")
        row = rows[0]

        category = str(row.leaf)
        consistency_ok = str(row.issue).lower() != "true"
        grasp_type = str(row.gt).rsplit("#", 1)[-1] if row.gt else None
        source = "rule" if grasp_type else "none"

        if grasp_type is None and self.embedding_model is not None:
            try:
                preds = self.embedding_model.predict_tail(category, "recommendedGraspType", k=1)
            except KeyError:
                preds = []
            if preds:
                grasp_type = preds[0][0]
                source = "embedding"

        rate = feedback.success_rate(self.store, category, grasp_type) if grasp_type else None
        return GraspAdvice(
            instance=str(instance_uri),
            category=category,
            grasp_type=grasp_type,
            confidence=float(row.conf),
            consistency_ok=consistency_ok,
            source=source,
            known_success_rate=rate,
        )

    def explain(self, advice: GraspAdvice) -> str:
        text = (
            f"{advice.category}: recommend {advice.grasp_type or 'no grasp type available'} "
            f"(source: {advice.source}, detector confidence {advice.confidence:.2f})"
        )
        if not advice.consistency_ok:
            text += " - WARNING: pose is inconsistent with known stable orientations, re-check before grasping."
        if advice.known_success_rate is not None:
            text += f" - historical success rate for this grasp: {advice.known_success_rate:.0%}."
        return text
