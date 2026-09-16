#!/usr/bin/env python3
"""podge_to_spatialkg_bridge: polls PODGE and registers every result as a
live sighting in SpatialKG, so "where is X" answers reflect what the robot
is currently seeing, not just the loaded sample scene.

Same PODGE-interface caveat as ros/graspkg_ros/scripts/podge_bridge_node.py
- I don't have object_detector_msgs' real service definition, so
_call_podge() below is the same informed guess, duplicated rather than
shared across the two independent catkin packages. Fix both copies once
you've confirmed the real interface (see graspkg_ros/README.md's checklist).

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
    from object_detector_msgs.srv import get_poses, get_posesRequest

    _PODGE_IMPORT_OK = True
    _PODGE_IMPORT_ERROR = ""
except ImportError as exc:
    _PODGE_IMPORT_OK = False
    _PODGE_IMPORT_ERROR = str(exc)


class PODGEToSpatialKGBridge:
    def __init__(self):
        rospy.init_node("podge_to_spatialkg_bridge")
        self.podge_service_name = rospy.get_param("~podge_service", "/pose_estimator/get_poses")
        self.color_topic = rospy.get_param("~color_topic", "/hsrb/head_rgbd_sensor/rgb/image_rect_color")
        self.room_id = rospy.get_param("~room_id", "Kitchen")
        poll_period = rospy.get_param("~poll_period", 10.0)

        rospy.wait_for_service("spatialkg_node/register_detection")
        self._register = rospy.ServiceProxy("spatialkg_node/register_detection", RegisterDetection)

        rospy.Timer(rospy.Duration(poll_period), self._poll)
        rospy.loginfo(
            "podge_to_spatialkg_bridge: ready, polling %s every %.1fs for room '%s' (import ok: %s)",
            self.podge_service_name, poll_period, self.room_id, _PODGE_IMPORT_OK,
        )

    def _call_podge(self):
        """Same guessed interface as podge_bridge_node.py - fix here too
        once confirmed. Returns [(object_name, confidence, geometry_msgs/Pose)]."""
        if not _PODGE_IMPORT_OK:
            raise RuntimeError(f"object_detector_msgs.srv.get_poses not importable: {_PODGE_IMPORT_ERROR}")
        rgb = rospy.wait_for_message(self.color_topic, Image, timeout=5.0)
        rospy.wait_for_service(self.podge_service_name, timeout=5.0)
        call = rospy.ServiceProxy(self.podge_service_name, get_poses)
        resp = call(get_posesRequest(image=rgb))
        return [(p.name, float(p.confidence), p.pose) for p in resp.poses]

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
