import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from rdflib import RDF
from rdflib.namespace import OWL

from graspkg import feedback, reasoning
from graspkg.detectors import Detection, SimulatedPODGEStream, YCBV_CLASS_MAP
from graspkg.graph_creation import add_detection
from graspkg.store import GRASP, GraspStore


@pytest.fixture
def store():
    s = GraspStore()
    s.load_default_ontology()
    reasoning.materialize_rdfs(s)
    return s


def test_ontology_declares_all_twelve_classes(store):
    for class_name in YCBV_CLASS_MAP.values():
        assert (GRASP[class_name], RDF.type, OWL.Class) in store.graph


def test_mug_inherits_handle_graspable(store):
    det = Detection("025_mug", 0.9, (0.5, 0.0, 0.8), (0, 0, 0, 1))
    inst = add_detection(store, det)
    reasoning.materialize_rdfs(store)
    types = set(store.graph.objects(inst, RDF.type))
    assert GRASP.HandleGraspable in types
    assert GRASP.Mug in types


def test_rule_derives_grasp_type_for_known_category(store):
    det = Detection("025_mug", 0.9, (0.5, 0.0, 0.8), (0, 0, 0, 1))
    inst = add_detection(store, det)
    reasoning.materialize_rdfs(store)
    reasoning.run_rules(store)
    derived = list(store.graph.objects(inst, GRASP.derivedGraspType))
    assert GRASP.HandleGrasp in derived


def test_consistency_check_flags_bad_pose(store):
    det = Detection("025_mug", 0.9, (0.5, 0.0, 0.8), (0.2, 0.9, 0.3, 0.15))
    inst = add_detection(store, det)
    reasoning.materialize_rdfs(store)
    reasoning.check_pose_consistency(store)
    flags = list(store.graph.objects(inst, GRASP.hasConsistencyIssue))
    assert flags and str(flags[0]) == "true"


def test_consistency_check_accepts_good_pose(store):
    det = Detection("025_mug", 0.9, (0.5, 0.0, 0.8), (0.0, 0.0, 0.0, 1.0))
    inst = add_detection(store, det)
    reasoning.materialize_rdfs(store)
    reasoning.check_pose_consistency(store)
    flags = list(store.graph.objects(inst, GRASP.hasConsistencyIssue))
    assert not flags


def test_feedback_updates_success_rate(store):
    det = Detection("025_mug", 0.9, (0.5, 0.0, 0.8), (0, 0, 0, 1))
    inst = add_detection(store, det)
    _, rate1 = feedback.record_outcome(store, inst, "HandleGraspable", "HandleGrasp", True)
    assert rate1 == 1.0
    _, rate2 = feedback.record_outcome(store, inst, "HandleGraspable", "HandleGrasp", False)
    assert rate2 == 0.5


def test_simulated_stream_only_emits_configured_classes():
    stream = SimulatedPODGEStream(seed=3)
    for det in stream.sample(50):
        assert det.object_name in YCBV_CLASS_MAP


def test_add_detection_rejects_unknown_object(store):
    det = Detection("999_unknown_widget", 0.9, (0.5, 0.0, 0.8), (0, 0, 0, 1))
    with pytest.raises(ValueError):
        add_detection(store, det)
