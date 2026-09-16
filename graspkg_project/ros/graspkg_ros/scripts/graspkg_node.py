#!/usr/bin/env python3
"""graspkg_node: owns the GraspKG knowledge graph and exposes it to the rest
of the ROS network.

Services:
  ~add_detection      - ingest one perception detection, get immediate advice back
  ~get_grasp_advice   - re-query advice for an already-known instance
  ~report_outcome     - feed a real grasp result back into the KG (LO8)

Topic:
  ~grasp_advice (graspkg_ros/GraspAdvice) - published every time a detection
  is ingested, for nodes that want a fire-and-forget subscription instead of
  a service call (see grasp_executor_client_example.py).

Requires the pure-python `graspkg` package to be importable - either
`pip install -e /path/to/graspkg_project` or add it to PYTHONPATH before
launching this node. It does not need ROS at all and can be developed/tested
independently (see ../../scripts and ../../tests).
"""
import rospy

from graspkg import feedback as fb
from graspkg import reasoning
from graspkg.advisory_service import GraspAdvisoryService
from graspkg.detectors import Detection
from graspkg.embeddings import TransE, triples_from_store
from graspkg.graph_creation import add_detection
from graspkg.store import GraspStore

from graspkg_ros.msg import GraspAdvice as GraspAdviceMsg
from graspkg_ros.srv import (
    AddDetection,
    AddDetectionResponse,
    GetGraspAdvice,
    GetGraspAdviceResponse,
    ReportGraspOutcome,
    ReportGraspOutcomeResponse,
)


class GraspKGNode:
    def __init__(self):
        rospy.init_node("graspkg_node")

        self.store = GraspStore()
        self.store.load_default_ontology()
        reasoning.materialize_rdfs(self.store)

        rospy.loginfo("graspkg_node: training embedding refinement layer...")
        triples = triples_from_store(self.store)
        self.embed_model = TransE(triples, dim=16, seed=0)
        self.embed_model.fit(epochs=200, lr=0.05)

        self.service = GraspAdvisoryService(self.store, embedding_model=self.embed_model)
        self.advice_pub = rospy.Publisher("~grasp_advice", GraspAdviceMsg, queue_size=10)

        rospy.Service("~add_detection", AddDetection, self._handle_add_detection)
        rospy.Service("~get_grasp_advice", GetGraspAdvice, self._handle_get_advice)
        rospy.Service("~report_outcome", ReportGraspOutcome, self._handle_report_outcome)

        rospy.loginfo("graspkg_node: ready (%d triples loaded)", len(self.store))

    def _handle_add_detection(self, req):
        resp = AddDetectionResponse()
        det = Detection(
            object_name=req.object_name,
            confidence=req.confidence,
            position=(req.position_x, req.position_y, req.position_z),
            orientation=(req.quat_x, req.quat_y, req.quat_z, req.quat_w),
            frame_id=req.frame_id or "head_rgbd_sensor_rgb_frame",
        )
        try:
            inst = add_detection(self.store, det)
        except ValueError as exc:
            resp.success = False
            resp.message = str(exc)
            return resp

        reasoning.materialize_rdfs(self.store)
        reasoning.run_rules(self.store)
        reasoning.check_pose_consistency(self.store)

        advice = self.service.advise(inst)
        resp.success = True
        resp.instance_uri = str(inst)
        resp.category = advice.category
        resp.grasp_type = advice.grasp_type or ""
        resp.consistency_ok = advice.consistency_ok
        resp.source = advice.source
        resp.known_success_rate = advice.known_success_rate if advice.known_success_rate is not None else -1.0
        resp.message = self.service.explain(advice)

        msg = GraspAdviceMsg()
        msg.header.stamp = rospy.Time.now()
        msg.instance_uri = resp.instance_uri
        msg.category = resp.category
        msg.grasp_type = resp.grasp_type
        msg.detector_confidence = advice.confidence
        msg.consistency_ok = advice.consistency_ok
        msg.source = advice.source
        msg.known_success_rate = resp.known_success_rate
        msg.position_x = req.position_x
        msg.position_y = req.position_y
        msg.position_z = req.position_z
        msg.frame_id = req.frame_id or "head_rgbd_sensor_rgb_frame"
        self.advice_pub.publish(msg)
        return resp

    def _handle_get_advice(self, req):
        from rdflib import URIRef

        resp = GetGraspAdviceResponse()
        try:
            advice = self.service.advise(URIRef(req.instance_uri))
        except ValueError as exc:
            resp.success = False
            resp.explanation = str(exc)
            return resp
        resp.success = True
        resp.category = advice.category
        resp.grasp_type = advice.grasp_type or ""
        resp.detector_confidence = advice.confidence
        resp.consistency_ok = advice.consistency_ok
        resp.source = advice.source
        resp.known_success_rate = advice.known_success_rate if advice.known_success_rate is not None else -1.0
        resp.explanation = self.service.explain(advice)
        return resp

    def _handle_report_outcome(self, req):
        from rdflib import URIRef

        resp = ReportGraspOutcomeResponse()
        try:
            advice = self.service.advise(URIRef(req.instance_uri))
        except ValueError as exc:
            resp.success = False
            resp.message = str(exc)
            return resp
        if not advice.grasp_type:
            resp.success = False
            resp.message = "no grasp type on record for this instance"
            return resp
        _, rate = fb.record_outcome(
            self.store, URIRef(req.instance_uri), advice.category, advice.grasp_type, req.succeeded
        )
        resp.success = True
        resp.updated_success_rate = rate
        resp.message = (
            f"logged outcome; running success rate for {advice.category}/{advice.grasp_type} "
            f"is now {rate:.0%}"
        )
        return resp


if __name__ == "__main__":
    GraspKGNode()
    rospy.spin()
