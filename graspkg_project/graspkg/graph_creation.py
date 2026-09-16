"""(g) - graph creation: turns Detection objects into RDF individuals against
the GraspKG ontology's TBox."""
from __future__ import annotations

from datetime import datetime, timezone

from rdflib import RDF, Literal
from rdflib.namespace import XSD

from .detectors import Detection, YCBV_CLASS_MAP
from .store import GRASP, GraspStore


def add_detection(store: GraspStore, det: Detection):
    """Asserts one detection as a new grasp:DetectedObject individual.
    Returns the new instance's URI."""
    class_name = YCBV_CLASS_MAP.get(det.object_name)
    if class_name is None:
        raise ValueError(
            f"'{det.object_name}' is not one of the 12 objects PODGE is "
            f"configured for (see detectors.YCBV_CLASS_MAP)."
        )
    inst = store.new_instance_uri(prefix=class_name.lower())
    cls = GRASP[class_name]
    ts = datetime.fromtimestamp(det.timestamp, tz=timezone.utc)

    store.add(
        [
            (inst, RDF.type, cls),
            (inst, RDF.type, GRASP.DetectedObject),
            (inst, GRASP.leafClass, Literal(class_name, datatype=XSD.string)),
            (inst, GRASP.hasConfidence, Literal(det.confidence, datatype=XSD.float)),
            (inst, GRASP.detectedAt, Literal(ts.isoformat(), datatype=XSD.dateTime)),
            (inst, GRASP.positionX, Literal(det.position[0], datatype=XSD.float)),
            (inst, GRASP.positionY, Literal(det.position[1], datatype=XSD.float)),
            (inst, GRASP.positionZ, Literal(det.position[2], datatype=XSD.float)),
            (inst, GRASP.quatX, Literal(det.orientation[0], datatype=XSD.float)),
            (inst, GRASP.quatY, Literal(det.orientation[1], datatype=XSD.float)),
            (inst, GRASP.quatZ, Literal(det.orientation[2], datatype=XSD.float)),
            (inst, GRASP.quatW, Literal(det.orientation[3], datatype=XSD.float)),
        ]
    )
    return inst


def add_detections(store: GraspStore, detections):
    return [add_detection(store, d) for d in detections]
