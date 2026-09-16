import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from rdflib import RDF
from rdflib.namespace import OWL

from spatialkg import evolution, reasoning
from spatialkg.reference_data import FURNITURE_CLASSES, YCBV_LEAF_CLASSES
from spatialkg.query_service import SpatialQueryService
from spatialkg.scene_loader import LiveDetection, add_live_detection, load_scene_file
from spatialkg.store import SP, SpatialStore

SAMPLE_SCENE = Path(__file__).resolve().parent.parent / "spatialkg" / "sample_data" / "sample_scene.json"


@pytest.fixture
def loaded_store():
    store = SpatialStore()
    store.load_default_ontology()
    load_scene_file(store, SAMPLE_SCENE)
    reasoning.materialize_rdfs(store)
    reasoning.run_rules(store)
    return store


def test_ontology_declares_all_classes():
    store = SpatialStore()
    store.load_default_ontology()
    for class_name in list(YCBV_LEAF_CLASSES) + list(FURNITURE_CLASSES):
        assert (SP[class_name], RDF.type, OWL.Class) in store.graph


def test_scene_loads_expected_counts():
    store = SpatialStore()
    store.load_default_ontology()
    report = load_scene_file(store, SAMPLE_SCENE)
    assert report["scans"] == 2
    assert report["objects"] == 7 + 8
    assert report["relationships"] == 4 + 5
    assert report["same_instance_links"] == 7  # 7 objects present in both scans


def test_room_propagation_is_recursive(loaded_store):
    # Mug is *supportedBy* Shelf in the later scan; Shelf itself is only
    # linked to Kitchen via locatedIn - the mug must inherit that
    # transitively, which is the point of the recursive rule.
    rows = loaded_store.select(
        """
        PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#>
        SELECT ?room WHERE {
            ?obj sp:leafClass "Mug" ; sp:supportedBy ?anchor ; sp:locatedIn ?room .
            ?anchor sp:leafClass "Shelf" .
        }
        """
    )
    assert rows and str(rows[0].room) == str(SP.Kitchen)


def test_reachability_is_transitive(loaded_store):
    rows = loaded_store.select(
        "PREFIX sp: <http://v4r.tuwien.ac.at/spatialkg#> SELECT ?r WHERE { sp:Kitchen sp:reachableFrom ?r }"
    )
    reachable = {str(r.r) for r in rows}
    assert str(SP.LivingRoom) in reachable  # 2 hops via Corridor
    assert str(SP.Corridor) in reachable


def test_staleness_flags_superseded_observations(loaded_store):
    n = reasoning.check_staleness(loaded_store, now=datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc))
    assert n == 7  # exactly the 7 objects only re-confirmed at t0, superseded by t1


def test_locate_reports_the_most_recent_sighting(loaded_store):
    reasoning.check_staleness(loaded_store, now=datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc))
    service = SpatialQueryService(loaded_store)
    answer = service.locate("Mug")
    assert answer.found and answer.room == "Kitchen"
    assert answer.support_chain == ["Mug", "Shelf", "Kitchen"]
    assert answer.is_stale is False


def test_locate_is_honest_about_unknown_objects(loaded_store):
    service = SpatialQueryService(loaded_store)
    answer = service.locate("PowerDrill")
    assert not answer.found
    assert answer.source == "none"


def test_correction_becomes_the_new_latest_sighting(loaded_store):
    evolution.apply_correction(loaded_store, "MustardBottle", "LivingRoom", corrected_by="user")
    reasoning.run_rules(loaded_store)
    service = SpatialQueryService(loaded_store)
    answer = service.locate("MustardBottle")
    assert answer.room == "LivingRoom"
    assert answer.history_note is not None and "Kitchen" in answer.history_note


def test_live_detection_can_be_added_without_a_scene_file():
    store = SpatialStore()
    store.load_default_ontology()
    store.add([(SP.Kitchen, RDF.type, SP.Room)])
    det = LiveDetection(object_name="025_mug", confidence=0.9, position=(1.0, 0.5, 0.8), room_id="Kitchen")
    inst = add_live_detection(store, det)
    assert (inst, SP.locatedIn, SP.Kitchen) in store.graph
