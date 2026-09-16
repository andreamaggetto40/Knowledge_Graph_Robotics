#!/usr/bin/env python3
"""spatialkg_to_graspkg_handoff: the concrete link between the primary
project (SpatialKG - where is it) and the secondary extension (GraspKG -
how do I hold it). Exposes ~find_and_grasp: call SpatialKG's locate_object,
and if it found a fresh sighting, feed that position straight into
GraspKG's add_detection to get a grasp type back.

This node deliberately knows about both graspkg_ros and spatialkg_ros;
neither of those packages needs to know about each other or about this
one - the coupling lives here and only here.
"""
import rospy

from spatialkg_ros.srv import FindAndGrasp, FindAndGraspResponse, LocateObject

from graspkg_ros.srv import AddDetection

# SpatialKG's leaf class names (spatialkg/reference_data.py) match GraspKG's
# leaf class names (graspkg/reference_data.py) one-for-one for the 12
# PODGE/YCB-V classes, but GraspKG's add_detection wants the original
# object_name string (e.g. "025_mug"), not the class name ("Mug") - invert
# spatialkg's YCBV_CLASS_MAP here rather than duplicating a second copy of it.
_CLASS_TO_OBJECT_NAME = {
    "MasterChefCan": "002_master_chef_can", "CrackerBox": "003_cracker_box",
    "TomatoSoupCan": "005_tomato_soup_can", "MustardBottle": "006_mustard_bottle",
    "GelatinBox": "009_gelatin_box", "PottedMeatCan": "010_potted_meat_can",
    "Banana": "011_banana", "BleachCleanser": "021_bleach_cleanser",
    "Bowl": "024_bowl", "Mug": "025_mug", "PowerDrill": "035_power_drill",
    "FoamBrick": "061_foam_brick",
}


class SpatialToGraspHandoff:
    def __init__(self):
        rospy.init_node("spatialkg_to_graspkg_handoff")
        rospy.wait_for_service("spatialkg_node/locate_object")
        rospy.wait_for_service("graspkg_node/add_detection")
        self._locate = rospy.ServiceProxy("spatialkg_node/locate_object", LocateObject)
        self._add_detection = rospy.ServiceProxy("graspkg_node/add_detection", AddDetection)
        rospy.Service("~find_and_grasp", FindAndGrasp, self._handle)
        rospy.loginfo("spatialkg_to_graspkg_handoff: ready")

    def _handle(self, req):
        resp = FindAndGraspResponse()
        location = self._locate(query_class=req.query_class)
        resp.found = location.found
        resp.room = location.room
        resp.is_stale = location.is_stale

        if not location.found:
            resp.success = True
            resp.message = f"can't grasp {req.query_class} - not currently located: {location.explanation}"
            return resp
        if location.is_stale:
            resp.success = True
            resp.message = f"{req.query_class}'s last known location is stale - re-scan before grasping"
            return resp

        object_name = _CLASS_TO_OBJECT_NAME.get(req.query_class)
        if object_name is None:
            resp.success = False
            resp.message = f"{req.query_class} is not one of GraspKG's 12 grasp-known classes"
            return resp

        # SpatialKG tracks position but not orientation, so we hand GraspKG
        # an identity quaternion here - fine for deciding a grasp *type*
        # from category, but GraspKG's pose-consistency check may flag it
        # for categories whose stable orientation isn't upright. Extend
        # LiveDetection/RegisterDetection with orientation if PODGE gives
        # you one and this matters for your use case.
        grasp = self._add_detection(
            object_name=object_name,
            confidence=location.confidence if location.confidence >= 0 else 0.5,
            position_x=location.position_x, position_y=location.position_y, position_z=location.position_z,
            quat_x=0.0, quat_y=0.0, quat_z=0.0, quat_w=1.0,
            frame_id="",
        )
        resp.success = True
        resp.grasp_type = grasp.grasp_type
        resp.consistency_ok = grasp.consistency_ok
        resp.message = f"{req.query_class} found in {resp.room}; " + grasp.message
        return resp


if __name__ == "__main__":
    SpatialToGraspHandoff()
    rospy.spin()
