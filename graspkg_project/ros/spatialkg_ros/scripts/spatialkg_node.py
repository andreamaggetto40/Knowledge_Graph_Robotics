#!/usr/bin/env python3
"""spatialkg_node: owns the SpatialKG knowledge graph and exposes it as a
"System of Record" for sasha_gpt (or anything else) to query.

Services:
  ~register_scene     - load a 3DSSG-format scene file (see spatialkg/sample_data)
  ~register_detection  - feed one live PODGE sighting into the graph
  ~locate_object       - the main query: "where is X, and how sure are we"
  ~apply_correction    - a human/LLM correction overrides a wrong/stale fact (LO8)

At startup this loads the ontology and the sample scene automatically (set
~scene_file to "" to start empty). Rules are re-run after every mutation so
~locate_object always sees the latest recursive closure.

Requires the pure-python `spatialkg` package importable - same story as
graspkg_ros: `pip install -e /path/to/graspkg_project` first.
"""
import rospy

from spatialkg import evolution, reasoning
from spatialkg.embeddings import ComplEx, triples_from_store
from spatialkg.query_service import SpatialQueryService
from spatialkg.scene_loader import LiveDetection, add_live_detection, load_scene_file
from spatialkg.store import SpatialStore

from spatialkg_ros.srv import (
    ApplyCorrection,
    ApplyCorrectionResponse,
    LocateObject,
    LocateObjectResponse,
    RegisterDetection,
    RegisterDetectionResponse,
    RegisterScene,
    RegisterSceneResponse,
)

import os
import spatialkg as _spatialkg_pkg

# Resolve the bundled sample scene via the *installed* spatialkg package
# location (works via `pip install -e .` or a real install), not a relative
# path from this script - this file gets copied into a catkin workspace
# far away from graspkg_project/spatialkg/, so a path guess relative to
# __file__ would silently point nowhere once deployed.
_DEFAULT_SCENE = os.path.join(os.path.dirname(_spatialkg_pkg.__file__), "sample_data", "sample_scene.json")


class SpatialKGNode:
    def __init__(self):
        rospy.init_node("spatialkg_node")

        self.store = SpatialStore()
        self.store.load_default_ontology()
        reasoning.materialize_rdfs(self.store)

        scene_file = rospy.get_param("~scene_file", _DEFAULT_SCENE)
        if scene_file:
            try:
                report = load_scene_file(self.store, scene_file)
                rospy.loginfo("spatialkg_node: loaded scene %s -> %s", scene_file, report)
            except FileNotFoundError:
                rospy.logwarn("spatialkg_node: no scene file at %s, starting empty", scene_file)

        reasoning.materialize_rdfs(self.store)
        reasoning.run_rules(self.store)
        reasoning.check_staleness(self.store)

        self._retrain_embeddings()
        self.service = SpatialQueryService(self.store, embedding_model=self.embed_model)

        rospy.Service("~register_scene", RegisterScene, self._handle_register_scene)
        rospy.Service("~register_detection", RegisterDetection, self._handle_register_detection)
        rospy.Service("~locate_object", LocateObject, self._handle_locate_object)
        rospy.Service("~apply_correction", ApplyCorrection, self._handle_apply_correction)

        rospy.loginfo("spatialkg_node: ready (%d triples loaded)", len(self.store))

    def _retrain_embeddings(self):
        triples = triples_from_store(self.store)
        self.embed_model = ComplEx(triples, dim=16, seed=0) if triples else None
        if self.embed_model:
            self.embed_model.fit(epochs=200, lr=0.05)

    def _refresh(self):
        reasoning.materialize_rdfs(self.store)
        reasoning.run_rules(self.store)
        reasoning.check_staleness(self.store)
        self._retrain_embeddings()
        self.service = SpatialQueryService(self.store, embedding_model=self.embed_model)

    def _handle_register_scene(self, req):
        resp = RegisterSceneResponse()
        try:
            report = load_scene_file(self.store, req.scene_file_path)
        except Exception as exc:
            resp.success = False
            resp.message = str(exc)
            return resp
        self._refresh()
        resp.success = True
        resp.objects_loaded = report["objects"]
        resp.relationships_loaded = report["relationships"]
        resp.message = f"loaded {report['scans']} scan(s)"
        return resp

    def _handle_register_detection(self, req):
        resp = RegisterDetectionResponse()
        det = LiveDetection(
            object_name=req.object_name,
            confidence=req.confidence,
            position=(req.position_x, req.position_y, req.position_z),
            room_id=req.room_id,
        )
        try:
            inst = add_live_detection(self.store, det)
        except ValueError as exc:
            resp.success = False
            resp.message = str(exc)
            return resp
        self._refresh()
        resp.success = True
        resp.instance_uri = str(inst)
        resp.message = "registered"
        return resp

    def _handle_locate_object(self, req):
        resp = LocateObjectResponse()
        answer = self.service.locate(req.query_class)
        resp.success = True
        resp.found = answer.found
        resp.room = answer.room or ""
        resp.support_chain = answer.support_chain
        resp.observed_at = answer.observed_at or ""
        resp.is_stale = bool(answer.is_stale)
        resp.source = answer.source
        resp.confidence = answer.confidence if answer.confidence is not None else -1.0
        if answer.position:
            resp.position_x, resp.position_y, resp.position_z = answer.position
        resp.history_note = answer.history_note or ""
        resp.explanation = self.service.explain(answer)
        return resp

    def _handle_apply_correction(self, req):
        resp = ApplyCorrectionResponse()
        inst = evolution.apply_correction(self.store, req.query_class, req.correct_room_id, req.corrected_by or "user")
        self._refresh()
        resp.success = True
        resp.instance_uri = str(inst)
        resp.message = f"{req.query_class} corrected to {req.correct_room_id} by {req.corrected_by}"
        return resp


if __name__ == "__main__":
    SpatialKGNode()
    rospy.spin()
