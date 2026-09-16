"""(LO8) KG evolution: writes real grasp outcomes back into the graph and
tracks a rolling per-(category, grasp type) success rate."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from rdflib import RDF, Literal
from rdflib.namespace import XSD

from .store import GRASP, GraspStore


def _stat_uri(category_name: str, grasp_type_name: str):
    digest = hashlib.sha1(f"{category_name}|{grasp_type_name}".encode()).hexdigest()[:10]
    return GRASP[f"stat_{digest}"]


def get_counts(store: GraspStore, category_name: str, grasp_type_name: str):
    stat = _stat_uri(category_name, grasp_type_name)
    successes = next(iter(store.graph.objects(stat, GRASP.successCount)), None)
    attempts = next(iter(store.graph.objects(stat, GRASP.attemptCount)), None)
    return (
        int(successes) if successes is not None else 0,
        int(attempts) if attempts is not None else 0,
    )


def record_outcome(store: GraspStore, instance_uri, category_name: str, grasp_type_name: str,
                    success: bool, timestamp: Optional[float] = None):
    """Logs one grasp attempt and updates the running success-rate statistic
    for (category, grasp type). Returns (attempt_uri, new_success_rate)."""
    ts = datetime.fromtimestamp(timestamp or datetime.now().timestamp(), tz=timezone.utc)
    attempt = store.new_instance_uri("attempt")
    grasp_type = GRASP[grasp_type_name]

    store.add(
        [
            (attempt, RDF.type, GRASP.GraspAttempt),
            (attempt, GRASP.attemptedOn, instance_uri),
            (attempt, GRASP.attemptedGraspType, grasp_type),
            (attempt, GRASP.attemptSucceeded, Literal(success, datatype=XSD.boolean)),
            (attempt, GRASP.attemptedAt, Literal(ts.isoformat(), datatype=XSD.dateTime)),
        ]
    )

    stat = _stat_uri(category_name, grasp_type_name)
    successes, attempts = get_counts(store, category_name, grasp_type_name)
    successes += int(success)
    attempts += 1
    store.graph.remove((stat, GRASP.successCount, None))
    store.graph.remove((stat, GRASP.attemptCount, None))
    store.add(
        [
            (stat, RDF.type, GRASP.GraspTypeStat),
            (stat, GRASP.forCategory, GRASP[category_name]),
            (stat, GRASP.forGraspType, grasp_type),
            (stat, GRASP.successCount, Literal(successes, datatype=XSD.integer)),
            (stat, GRASP.attemptCount, Literal(attempts, datatype=XSD.integer)),
        ]
    )
    return attempt, successes / attempts


def success_rate(store: GraspStore, category_name: str, grasp_type_name: str):
    successes, attempts = get_counts(store, category_name, grasp_type_name)
    if attempts == 0:
        return None
    return successes / attempts


def is_underperforming(store: GraspStore, category_name: str, grasp_type_name: str,
                        threshold: float = 0.5, min_attempts: int = 3) -> bool:
    successes, attempts = get_counts(store, category_name, grasp_type_name)
    if attempts < min_attempts:
        return False
    return successes / attempts < threshold
