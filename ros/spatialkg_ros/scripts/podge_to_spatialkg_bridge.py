#!/usr/bin/env python3
"""podge_to_spatialkg_bridge: polls PODGE and registers every result as a
live sighting in SpatialKG, so "where is X" answers reflect what the robot
is currently seeing, not just the loaded sample scene.

VERIFIED interface - same as ros/graspkg_ros/scripts/podge_bridge_node.py,
duplicated rather than shared across the two independent catkin packages
(see that file's docstring for the full detail on what was confirmed
against grasping_pipeline's own source and why: PODGE is two actionlib
`robokudo_msgs/GenericImgProcAnnotatorAction` servers - detector then pose
estimator - not one combined service).

Which room the robot is currently in is itself a simplification here -
`~room_id` is a fixed param rather than coming from localization/room
classification. Wire it to whatever room-estimation you already have (the
HSR's AMCL pose + a room-containment polygon, most likely) once this needs
to work while the robot is actually moving between rooms.
"""
import rospy
from sensor_msgs.msg import Image

from spatialkg_ros.srv import RegisterDetection

try:
    from actionlib import SimpleActionClient
    from actionlib_msgs.msg import GoalStatus
    from robokudo_msgs.msg import GenericImgProcAnnotatorAction, GenericImgProcAnnotatorGoal

    _PODGE_IMPORT_OK = True
    _PODGE_IMPORT_ERROR = ""
except ImportError as exc:
    _PODGE_IMPORT_OK = False
    _PODGE_IMPORT_ERROR = str(exc)


class PODGEToSpatialKGBridge:
    def __init__(self):
        rospy.init_node("podge_to_spatialkg_bridge")
        self.object_detector_topic = rospy.get_param("~object_detector_topic", "/object_detector/yolov8")
        self.pose_estimator_topic = rospy.get_param("~pose_estimator_topic", "/pose_estimator/gdrnet")
        self.rgb_topic = rospy.get_param("~color_topic", "/hsrb/head_rgbd_sensor/rgb/image_rect_color")
        self.depth_topic = rospy.get_param(
            "~depth_topic", "/hsrb/head_rgbd_sensor/depth_registered/image_rect_raw"
        )
        self.timeout = rospy.get_param("~timeout", 40.0)
        self.room_id = rospy.get_param("~room_id", "Kitchen")
        poll_period = rospy.get_param("~poll_period", 10.0)

        rospy.wait_for_service("spatialkg_node/register_detection")
        self._register = rospy.ServiceProxy("spatialkg_node/register_detection", RegisterDetection)

        rospy.Timer(rospy.Duration(poll_period), self._poll)
        rospy.loginfo(
            "podge_to_spatialkg_bridge: ready, polling %s + %s every %.1fs for room '%s' (import ok: %s)",
            self.object_detector_topic, self.pose_estimator_topic, poll_period, self.room_id, _PODGE_IMPORT_OK,
        )

    def _call_podge(self):
        """Same confirmed two-stage interface as podge_bridge_node.py.
        Returns [(object_name, confidence, geometry_msgs/Pose)]."""
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
            return []

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

    def _poll(self, _event):
        try:
            results = self._call_podge()
        except Exception as exc:
            rospy.logwarn_throttle(30, "podge_to_spatialkg_bridge: PODGE call failed: %s", exc)
            return
        for object_name, confidence, pose in results:
            try:
                self._register(
                    object_name=object_name,
                    confidence=confidence,
                    position_x=pose.position.x,
                    position_y=pose.position.y,
                    position_z=pose.position.z,
                    room_id=self.room_id,
                )
            except rospy.ServiceException as exc:
                rospy.logerr("podge_to_spatialkg_bridge: register_detection failed for %s: %s", object_name, exc)


if __name__ == "__main__":
    PODGEToSpatialKGBridge()
    rospy.spin()
