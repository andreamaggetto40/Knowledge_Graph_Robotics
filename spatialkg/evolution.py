"""(LO8) KG evolution: a correction is just a new, very recent, human- or
LLM-sourced Observation, linked by sameInstanceAs to whatever we previously
believed - so it automatically becomes the "most recent sighting" that
query_service.locate() reports, without any special-casing there. This
keeps the KG's memory append-only and auditable rather than silently
overwriting history.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rdflib import RDF, Literal
from rdflib.namespace import XSD

from .store import SP, SpatialStore


def apply_correction(store: SpatialStore, query_class: str, correct_room_id: str, corrected_by: str = "user", position=None):
    """Records `corrected_by`'s claim that `query_class` is actually in
    `correct_room_id` right now. `position`, if given, overrides where
    exactly within that room; otherwise the previous sighting's position is
    carried forward (better than no position at all, since locate() and the
    GraspKG hand-off both require one) - correcting the room without a
    precise new position is still an improvement over a stale/wrong room.
    Returns the new observation's URI."""
    previous = store.select(
        f"""
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT ?obj ?px ?py ?pz WHERE {{
            ?obj sp:leafClass "{query_class}" ; sp:observedAt ?t ;
                 sp:positionX ?px ; sp:positionY ?py ; sp:positionZ ?pz .
        }} ORDER BY DESC(?t) LIMIT 1
        """
    )
    if position is None:
        position = (float(previous[0].px), float(previous[0].py), float(previous[0].pz)) if previous else (0.0, 0.0, 0.0)

    now = datetime.now(tz=timezone.utc)
    inst = store.new_instance_uri(prefix=f"{query_class.lower()}_corrected")
    store.add(
        [
            (inst, RDF.type, SP[query_class]),
            (inst, SP.leafClass, Literal(query_class)),
            (inst, SP.locatedIn, SP[correct_room_id]),
            (inst, SP.positionX, Literal(position[0], datatype=XSD.float)),
            (inst, SP.positionY, Literal(position[1], datatype=XSD.float)),
            (inst, SP.positionZ, Literal(position[2], datatype=XSD.float)),
            (inst, SP.observedAt, Literal(now.isoformat(), datatype=XSD.dateTime)),
            (inst, SP.sourceScan, Literal(f"correction:{corrected_by}")),
            (inst, SP.correctedBy, Literal(corrected_by)),
            (inst, SP.isStale, Literal(False, datatype=XSD.boolean)),
        ]
    )
    if previous:
        prev_uri = previous[0].obj
        store.add([(inst, SP.sameInstanceAs, prev_uri), (prev_uri, SP.sameInstanceAs, inst)])
    return inst
