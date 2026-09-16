"""(g) - knowledge acquisition: turns a 3DSSG-format scene file (or a live
PODGE detection) into RDF individuals against SpatialKG's ontology.

`load_scene_file` reads the exact [subject_id, object_id, relationship_id,
relationship_name] relationship format 3DSSG actually uses, grouped by
scan - point it at the real relationships.json (and give it a matching
`objects` block, since 3DSSG itself keys geometry off separate point-cloud
files) once you have licensed access; nothing else in this module changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rdflib import RDF, Literal
from rdflib.namespace import XSD

from .reference_data import FURNITURE_CLASSES, YCBV_CLASS_MAP, YCBV_LEAF_CLASSES
from .store import SP, SpatialStore

# 3DSSG's own relationship vocabulary has ~20-27 predicates (Wald et al.
# 2020); this is the load-bearing subset for spatial hierarchy/containment.
# Extend freely - anything not in this map is skipped with a warning rather
# than crashing the load.
REL_NAME_TO_PROPERTY = {
    "standing on": SP.supportedBy,
    "supported by": SP.supportedBy,
    "inside": SP.insideOf,
    "hanging on": SP.hangingOn,
    "attached to": SP.attachedTo,
    "part of": SP.partOf,
}

_KNOWN_CLASSES = set(FURNITURE_CLASSES) | set(YCBV_LEAF_CLASSES)


def load_scene_file(store: SpatialStore, path) -> dict:
    """Loads rooms, every scan's objects/relationships, and derives
    sameInstanceAs links across scans of the same reference_scene that
    share an object id. Returns a small report dict for logging/tests."""
    data = json.loads(Path(path).read_text())
    report = {"rooms": 0, "scans": 0, "objects": 0, "relationships": 0, "same_instance_links": 0, "skipped_relationships": 0}

    for room in data.get("rooms", []):
        room_uri = SP[room["id"]]
        store.add([(room_uri, RDF.type, SP.Room)])
        for neighbour in room.get("adjacent_to", []):
            store.add([(room_uri, SP.adjacentRoom, SP[neighbour])])
        report["rooms"] += 1

    # (reference_scene, local object id) -> list of instance URIs, in scan order,
    # used to derive sameInstanceAs across rescans of the same physical room.
    instance_history: dict[tuple, list] = {}

    for scan in data.get("scans", []):
        report["scans"] += 1
        room_uri = SP[scan["room"]]
        scanned_at = scan["scanned_at"]
        local_id_to_uri = {}

        for obj in scan["objects"]:
            class_name = obj["class"]
            if class_name not in _KNOWN_CLASSES:
                raise ValueError(f"unknown class '{class_name}' in scan {scan['scan']} - add it to reference_data.py first")
            inst = store.new_instance_uri(prefix=class_name.lower())
            local_id_to_uri[obj["id"]] = inst
            store.add(
                [
                    (inst, RDF.type, SP[class_name]),
                    (inst, SP.leafClass, Literal(class_name)),
                    (inst, SP.locatedIn, room_uri),
                    (inst, SP.positionX, Literal(obj["position"][0], datatype=XSD.float)),
                    (inst, SP.positionY, Literal(obj["position"][1], datatype=XSD.float)),
                    (inst, SP.positionZ, Literal(obj["position"][2], datatype=XSD.float)),
                    (inst, SP.observedAt, Literal(scanned_at, datatype=XSD.dateTime)),
                    (inst, SP.sourceScan, Literal(scan["scan"])),
                ]
            )
            report["objects"] += 1

            key = (scan.get("reference_scene", scan["scan"]), obj["id"])
            instance_history.setdefault(key, []).append(inst)

        for subj_id, obj_id, _rel_id, rel_name in scan.get("relationships", []):
            prop = REL_NAME_TO_PROPERTY.get(rel_name)
            if prop is None:
                report["skipped_relationships"] += 1
                continue
            store.add([(local_id_to_uri[subj_id], prop, local_id_to_uri[obj_id])])
            report["relationships"] += 1

    for history in instance_history.values():
        for earlier, later in zip(history, history[1:]):
            store.add([(earlier, SP.sameInstanceAs, later), (later, SP.sameInstanceAs, earlier)])
            report["same_instance_links"] += 1

    return report


@dataclass
class LiveDetection:
    """What a PODGE-fed live sighting needs - mirrors graspkg.detectors.Detection
    but SpatialKG only cares about identity, position and room, not pose/grasp."""

    object_name: str  # a YCBV_CLASS_MAP key, e.g. "025_mug"
    confidence: float
    position: tuple
    room_id: str
    timestamp: float = None


def add_live_detection(store: SpatialStore, det: LiveDetection):
    """(g) for the live-robot path: one PODGE sighting -> one Observation,
    located in the given room. Returns the new instance URI."""
    class_name = YCBV_CLASS_MAP.get(det.object_name)
    if class_name is None:
        raise ValueError(f"'{det.object_name}' is not one of the 12 PODGE classes")
    ts = det.timestamp or datetime.now(tz=timezone.utc).timestamp()
    observed_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    inst = store.new_instance_uri(prefix=class_name.lower())
    store.add(
        [
            (inst, RDF.type, SP[class_name]),
            (inst, SP.leafClass, Literal(class_name)),
            (inst, SP.locatedIn, SP[det.room_id]),
            (inst, SP.positionX, Literal(det.position[0], datatype=XSD.float)),
            (inst, SP.positionY, Literal(det.position[1], datatype=XSD.float)),
            (inst, SP.positionZ, Literal(det.position[2], datatype=XSD.float)),
            (inst, SP.confidence, Literal(det.confidence, datatype=XSD.float)),
            (inst, SP.observedAt, Literal(observed_at.isoformat(), datatype=XSD.dateTime)),
            (inst, SP.sourceScan, Literal(f"live:{ts}")),
        ]
    )
    return inst
