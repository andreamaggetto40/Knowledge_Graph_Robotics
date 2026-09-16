"""The "System of Record" query API (Motivation/Problem from the one-pager):
this is what an LLM interface (sasha_gpt) calls to ground or verify an
answer about where something is, instead of hallucinating one from its
training data. Every answer carries its own provenance and staleness, so
"I don't actually know, last confirmed 6 hours ago" is a valid, honest
answer - which is the whole point of having a KG here rather than trusting
the LLM's memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .store import SP, SpatialStore


@dataclass
class LocationAnswer:
    query_class: str
    found: bool
    room: Optional[str] = None
    support_chain: list = field(default_factory=list)  # e.g. ["Mug", "Shelf", "Kitchen"]
    position: Optional[tuple] = None  # (x, y, z) of the most recent sighting, if any
    observed_at: Optional[str] = None
    is_stale: Optional[bool] = None
    source: str = "none"  # "observation" | "embedding" | "none"
    confidence: Optional[float] = None
    history_note: Optional[str] = None  # cross-scan re-localization note, if relevant


class SpatialQueryService:
    def __init__(self, store: SpatialStore, embedding_model=None):
        self.store = store
        self.embedding_model = embedding_model

    def locate(self, query_class: str) -> LocationAnswer:
        rows = self.store.select(
            f"""
            PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
            SELECT ?obj ?room ?anchor ?observedAt ?isStale ?conf ?px ?py ?pz WHERE {{
                ?obj sp:leafClass "{query_class}" ;
                     sp:locatedIn ?room ;
                     sp:observedAt ?observedAt ;
                     sp:positionX ?px ; sp:positionY ?py ; sp:positionZ ?pz .
                OPTIONAL {{ ?obj (sp:supportedBy|sp:insideOf|sp:hangingOn|sp:attachedTo) ?anchor }}
                OPTIONAL {{ ?obj sp:isStale ?isStale }}
                OPTIONAL {{ ?obj sp:confidence ?conf }}
            }}
            ORDER BY DESC(?observedAt)
            """
        )
        if not rows:
            return self._predicted_location(query_class)

        latest = rows[0]
        chain = [query_class]
        if latest.anchor is not None:
            anchor_class = self.store.graph.value(latest.anchor, SP.leafClass)
            if anchor_class is not None:
                chain.append(str(anchor_class))
        room_name = str(latest.room).rsplit("#", 1)[-1]
        chain.append(room_name)

        history_note = None
        if len(rows) > 1:
            earlier_rooms = {str(r.room).rsplit("#", 1)[-1] for r in rows[1:]}
            if earlier_rooms - {room_name}:
                history_note = (
                    f"also seen in {', '.join(sorted(earlier_rooms - {room_name}))} at an earlier time - "
                    f"reporting the most recent sighting"
                )

        return LocationAnswer(
            query_class=query_class,
            found=True,
            room=room_name,
            support_chain=chain,
            position=(float(latest.px), float(latest.py), float(latest.pz)),
            observed_at=str(latest.observedAt),
            is_stale=(str(latest.isStale).lower() == "true") if latest.isStale is not None else None,
            source="observation",
            confidence=float(latest.conf) if latest.conf is not None else None,
            history_note=history_note,
        )

    def _predicted_location(self, query_class: str) -> LocationAnswer:
        """No direct observation - fall back to embeddings to guess what
        this class of object is *typically* supported by (the one-pager's
        "predict a Table exists under a Plate" case), rather than claiming
        a room we have no evidence for."""
        if self.embedding_model is None:
            return LocationAnswer(query_class=query_class, found=False, source="none")
        try:
            preds = self.embedding_model.predict_tail(query_class, "supportedBy", k=1)
        except KeyError:
            preds = []
        if not preds:
            return LocationAnswer(query_class=query_class, found=False, source="none")
        predicted_anchor, _score = preds[0]
        return LocationAnswer(
            query_class=query_class,
            found=False,
            support_chain=[query_class, predicted_anchor],
            source="embedding",
        )

    def explain(self, answer: LocationAnswer) -> str:
        if answer.source == "observation":
            chain = " -> on/in ".join(answer.support_chain[:-1]) or answer.query_class
            text = f"{answer.query_class}: last confirmed {chain} in {answer.room}, observed at {answer.observed_at}"
            if answer.is_stale:
                text += " (STALE - this may no longer be accurate, re-verify before acting on it)"
            if answer.history_note:
                text += f"; {answer.history_note}"
            return text
        if answer.source == "embedding":
            return (
                f"{answer.query_class}: no direct sighting on record. Based on learned patterns, it is likely "
                f"supported by a {answer.support_chain[-1]} - this is a prediction, not an observation, and "
                f"should be flagged as such to the user rather than stated as fact."
            )
        return f"{answer.query_class}: no observation and no confident prediction - say so rather than guessing."
