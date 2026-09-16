#!/usr/bin/env python3
"""podge_bridge_node: calls PODGE (YOLOv8 + GDRNPP, brought up via
docker_compose/gdrnpp_yolov8.yml) on demand and forwards every result into
GraspKG's ~add_detection service.

VERIFIED, not guessed: read directly from grasping_pipeline's own source
(github.com/v4r-tuwien/grasping_pipeline - `src/object_detector.py` and
`src/pose_estimator.py`), which already talks to these exact same PODGE
containers for its own FindGrasp state, so this bridge now mirrors that
confirmed interface instead of the old `object_detector_msgs.get_poses`
guess:

- PODGE is not one combined pose service; it's two separate actionlib
  action servers, both using the SAME generic action type,
  `robokudo_msgs.msg.GenericImgProcAnnotatorAction`:
    1. the object detector (YOLOv8), default topic `/object_detector/yolov8`
       (grasping_pipeline's own `config/config.yaml` -> `object_detector_topic`)
       - goal: rgb, depth. result: class_names, class_confidences,
         bounding_boxes (sensor_msgs/RegionOfInterest[]), image (label image).
    2. the pose estimator (GDRNPP), default topic `/pose_estimator/gdrnet`
       (`config/config.yaml` -> `pose_estimator_topic`)
       - goal: rgb, depth, bb_detections, mask_detections, class_names,
         description (JSON-ish "{name: confidence, ...}" string - cosmetic,
         used for the estimator's own visualization/logging).
         result: class_names, class_confidences, pose_results
         (geometry_msgs/Pose[], same order as class_names).
- Both topics are configurable per grasping_pipeline's own config.yaml;
  the defaults above match its bundled config and your `DATASET=ycbv
  CONFIG=params_sasha.yaml` PODGE bring-up.
- Set grasping_pipeline's `config/config.yaml` -> `grasping_pipeline.dataset`
  to `ycb_bop`, not `ycb_ichores` or the bundled `tracebotcanister` default -
  `grasps/ycb_bop/*.npy` and `models/ycb_bop/*.stl` in that repo already
  cover exactly GraspKG's 12 classes (002_master_chef_can ... 061_foam_brick),
  so pose-based grasping works for all of them without adding new
  annotations. `ycb_ichores` uses different object IDs/names and is missing
  two of GraspKG's 12 classes (PowerDrill, FoamBrick).

STILL TO CONFIRM EMPIRICALLY (not verifiable from source alone): whether
PODGE with DATASET=ycbv already returns human-readable names like
"025_mug" directly in `class_names`, or generic ids like "obj_000019"
needing a mapping table (grasping_pipeline's `object_mapping.yaml` has
sections for `ycb_ichores`/`hope` but none for `ycb_bop`, which suggests
`ycb_bop` results already come back name-ready - but confirm by printing
`detection_result.class_names` once rather than assuming). If they come
back as `obj_NNNNNN`, add a lookup dict here the same shape as
`grasping_pipeline`'s `object_mapping.yaml` before calling add_detection.
"""
import rospy
from sensor_msgs.msg import Image

from graspkg_ros.msg import GraspAdvice
from graspkg_ros.srv import AddDetection, DetectAndAdvise, DetectAndAdviseResponse

try:
    from actionlib import SimpleActionClient
    from actionlib_msgs.msg import GoalStatus
    from robokudo_msgs.msg import GenericImgProcAnnotatorAction, GenericImgProcAnnotatorGoal

    _PODGE_IMPORT_OK = True
    _PODGE_IMPORT_ERROR = ""
except ImportError as exc:
    _PODGE_IMPORT_OK = False
    _PODGE_IMPORT_ERROR = str(exc)


class PODGEBridge:
    def __init__(self):
        rospy.init_node("podge_bridge_node")
        # Match grasping_pipeline's own config/config.yaml so both this
        # bridge and grasping_pipeline's internal FindGrasp state talk to
        # the exact same PODGE endpoints - override if your config.yaml
        # picks different topics (e.g. grounded_sam2 instead of yolov8).
        self.object_detector_topic = rospy.get_param("~object_detector_topic", "/object_detector/yolov8")
        self.pose_estimator_topic = rospy.get_param("~pose_estimator_topic", "/pose_estimator/gdrnet")
        self.rgb_topic = rospy.get_param("~color_topic", "/hsrb/head_rgbd_sensor/rgb/image_rect_color")
        self.depth_topic = rospy.get_param(
            "~depth_topic", "/hsrb/head_rgbd_sensor/depth_registered/image_rect_raw"
        )
        self.timeout = rospy.get_param("~timeout", 40.0)  # matches grasping_pipeline's default

        rospy.wait_for_service("graspkg_node/add_detection")
        self._add_detection = rospy.ServiceProxy("graspkg_node/add_detection", AddDetection)

        rospy.Service("~detect_and_advise", DetectAndAdvise, self._handle_detect_and_advise)
        rospy.loginfo(
            "podge_bridge_node: ready, will call %s then %s on request (import ok: %s)",
            self.object_detector_topic, self.pose_estimator_topic, _PODGE_IMPORT_OK,
        )
        if not _PODGE_IMPORT_OK:
            rospy.logwarn(
                "podge_bridge_node: %s - is robokudo_msgs on your ROS_PACKAGE_PATH? "
                "It's what grasping_pipeline itself uses for PODGE, so it should already "
                "be built alongside it.", _PODGE_IMPORT_ERROR,
            )

    def _call_podge(self):
        """Returns a list of (object_name, confidence, geometry_msgs/Pose),
        by calling PODGE's two action servers the same way grasping_pipeline's
        own object_detector.py / pose_estimator.py do."""
        if not _PODGE_IMPORT_OK:
            raise RuntimeError(f"robokudo_msgs.msg not importable: {_PODGE_IMPORT_ERROR}")

        rgb = rospy.wait_for_message(self.rgb_topic, Image, timeout=5.0)
        depth = rospy.wait_for_message(self.depth_topic, Image, timeout=5.0)

        detector = SimpleActionClient(self.object_detector_topic, GenericImgProcAnnotatorAction)
        if not detector.wait_for_server(timeout=rospy.Duration(self.timeout)):
            raise RuntimeError(f"object detector '{self.object_detector_topic}' didn't come up in time")
        detector.send_goal(GenericImgProcAnnotatorGoal(rgb=rgb, depth=depth))
        if not detector.wait_for_result(rospy.Duration(self.timeout)):
            raise RuntimeError("object detector timed out")
        detection = detector.get_result()
        if detector.get_state() != GoalStatus.SUCCEEDED or len(detection.class_names) == 0:
            return []  # nothing detected this frame - not an error

        pose_est = SimpleActionClient(self.pose_estimator_topic, GenericImgProcAnnotatorAction)
        if not pose_est.wait_for_server(timeout=rospy.Duration(self.timeout)):
            raise RuntimeError(f"pose estimator '{self.pose_estimator_topic}' didn't come up in time")
        pose_est.send_goal(GenericImgProcAnnotatorGoal(
            rgb=rgb, depth=depth,
            bb_detections=detection.bounding_boxes,
            class_names=detection.class_names,
        ))
        if not pose_est.wait_for_result(rospy.Duration(self.timeout)):
            raise RuntimeError("pose estimator timed out")
        poses = pose_est.get_result()
        if pose_est.get_state() != GoalStatus.SUCCEEDED or len(poses.pose_results) == 0:
            return []

        confidence_by_name = dict(zip(detection.class_names, detection.class_confidences))
        return [
            (name, float(confidence_by_name.get(name, 0.5)), pose)
            for name, pose in zip(poses.class_names, poses.pose_results)
        ]

    def _handle_detect_and_advise(self, req):
        resp = DetectAndAdviseResponse()
        try:
            results = self._call_podge()
        except Exception as exc:  # surface the failure to the caller, don't crash the node
            resp.success = False
            resp.message = f"PODGE call failed: {exc}"
            return resp

        wanted = set(req.object_name_filter) or None
        resp.advice = []
        for object_name, confidence, pose in results:
            if wanted is not None and object_name not in wanted:
                continue
            try:
                add_resp = self._add_detection(
                    object_name=object_name,
                    confidence=confidence,
                    position_x=pose.position.x,
                    position_y=pose.position.y,
                    position_z=pose.position.z,
                    quat_x=pose.orientation.x,
                    quat_y=pose.orientation.y,
                    quat_z=pose.orientation.z,
                    quat_w=pose.orientation.w,
                    frame_id="head_rgbd_sensor_rgb_frame",
                )
            except rospy.ServiceException as exc:
                rospy.logerr("podge_bridge_node: add_detection failed for %s: %s", object_name, exc)
                continue
            if not add_resp.success:
                rospy.logwarn("podge_bridge_node: %s", add_resp.message)
                continue

            advice = GraspAdvice()
            advice.instance_uri = add_resp.instance_uri
            advice.category = add_resp.category
            advice.grasp_type = add_resp.grasp_type
            advice.detector_confidence = confidence
            advice.consistency_ok = add_resp.consistency_ok
            advice.source = add_resp.source
            advice.known_success_rate = add_resp.known_success_rate
            advice.position_x = pose.position.x
            advice.position_y = pose.position.y
            advice.position_z = pose.position.z
            resp.advice.append(advice)

        resp.success = True
        resp.message = f"{len(resp.advice)} detection(s) added"
        return resp


if __name__ == "__main__":
    PODGEBridge()
    rospy.spin()
