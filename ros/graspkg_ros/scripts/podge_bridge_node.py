#!/usr/bin/env python3
"""podge_bridge_node: calls PODGE (YOLOv8 + GDRNPP, running as ROS services -
see docker_compose/gdrnpp_yolov8.yml) on demand and forwards every result
into GraspKG's ~add_detection service.

STATUS: PODGE's log shows it runs as a request/response service under (or
near) a `/pose_estimator/...` namespace, using message types from the
`object_detector_msgs` package that's already in your workspace - not a
continuously-published topic like the vision_msgs guess in an earlier
version of this file. I don't have the exact service name or field names
though, so `_call_podge()` below is an INFORMED GUESS, clearly isolated so
it's the only thing you need to fix. Confirm the real ones with:

    rosservice list | grep -iE "pose_estimator|yolo|gdrn"
    rosservice type <the name that shows up>
    find ~/HSR/catkin_ws/src/object_detector_msgs -name "*.srv" -o -name "*.msg" \\
        | xargs -I{} sh -c 'echo === {} ===; cat {}'

Everything else in this file - the ~detect_and_advise service, forwarding
into graspkg_node, building the response - stays correct regardless of what
_call_podge() ends up looking like, since it only depends on getting back a
plain list of (object_name, confidence, geometry_msgs/Pose) tuples.
"""
import rospy
from sensor_msgs.msg import Image

from graspkg_ros.msg import GraspAdvice
from graspkg_ros.srv import AddDetection, DetectAndAdvise, DetectAndAdviseResponse

try:
    # GUESS: shaped after the common two-stage 2D-detect -> 6D-pose-estimate
    # pattern used by GDRNPP ROS wrappers. Replace this import (and the body
    # of _call_podge below) with whatever `find ... -name "*.srv"` turns up.
    from object_detector_msgs.srv import get_poses, get_posesRequest

    _PODGE_IMPORT_OK = True
    _PODGE_IMPORT_ERROR = ""
except ImportError as exc:
    _PODGE_IMPORT_OK = False
    _PODGE_IMPORT_ERROR = str(exc)


class PODGEBridge:
    def __init__(self):
        rospy.init_node("podge_bridge_node")
        self.podge_service_name = rospy.get_param("~podge_service", "/pose_estimator/get_poses")
        self.color_topic = rospy.get_param(
            "~color_topic", "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
        )

        rospy.wait_for_service("graspkg_node/add_detection")
        self._add_detection = rospy.ServiceProxy("graspkg_node/add_detection", AddDetection)

        rospy.Service("~detect_and_advise", DetectAndAdvise, self._handle_detect_and_advise)
        rospy.loginfo(
            "podge_bridge_node: ready, will call %s on request (import ok: %s)",
            self.podge_service_name,
            _PODGE_IMPORT_OK,
        )
        if not _PODGE_IMPORT_OK:
            rospy.logwarn("podge_bridge_node: %s - fix _call_podge() before calling ~detect_and_advise", _PODGE_IMPORT_ERROR)

    def _call_podge(self):
        """Returns a list of (object_name, confidence, geometry_msgs/Pose).
        THE FUNCTION TO FIX once you've confirmed PODGE's real service."""
        if not _PODGE_IMPORT_OK:
            raise RuntimeError(f"object_detector_msgs.srv.get_poses not importable: {_PODGE_IMPORT_ERROR}")
        rgb = rospy.wait_for_message(self.color_topic, Image, timeout=5.0)
        rospy.wait_for_service(self.podge_service_name, timeout=5.0)
        call = rospy.ServiceProxy(self.podge_service_name, get_poses)
        resp = call(get_posesRequest(image=rgb))
        return [(p.name, float(p.confidence), p.pose) for p in resp.poses]

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
