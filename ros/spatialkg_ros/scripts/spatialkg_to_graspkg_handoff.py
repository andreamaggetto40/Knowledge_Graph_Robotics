#!/usr/bin/env python3
"""spatialkg_to_graspkg_handoff: the concrete link between the primary
project (SpatialKG - where is it), the secondary extension (GraspKG - how
do I hold it), and now the actual execution layer (grasping_pipeline -
go pick it up). Exposes ~find_and_grasp: call SpatialKG's locate_object,
feed the position into GraspKG's add_detection to get a grasp type back,
and - unless ~trigger_grasp is false - hand off to grasping_pipeline's
own LLM-facing entry point to really execute the pick, then report the
outcome back into GraspKG (closing the LO8 feedback loop for real).

This node deliberately knows about graspkg_ros, spatialkg_ros, AND
grasping_pipeline; none of those packages needs to know about each other
or about this one - the coupling lives here and only here.

VERIFIED against v4r-tuwien/grasping_pipeline (github.com/v4r-tuwien/
grasping_pipeline), not guessed - read from source, not the docs site,
which doesn't publish these specifics:
- `src/statemachine_llm.py`'s `LLM_Wrapper` runs an actionlib
  SimpleActionServer on '/robot_llm' (type `robot_llm.msg.RobotLLMAction`)
  whenever grasping_pipeline is launched with
  `roslaunch grasping_pipeline grasping_pipeline_statemachine.launch
  use_llm_state_machine:=true` (see launch/grasping_pipeline_statemachine.launch).
  This is grasping_pipeline's own ready-made "the LLM is the interface"
  entry point - exactly what the one-pager's architecture wants, and it
  already exists; nothing here needed to be invented.
- Goal fields (from `LLM_Wrapper.execute`): `task` - one of
  'handover' | 'placement' | 'detection' (grasping_pipeline/src/
  statemachine_llm.py's `self.behaviours` dict keys) - and `object_name`,
  the object to act on. Result field: `result`, a JSON string of the
  underlying SMACH state machine's final userdata, which always includes
  `status` set to that state machine's own terminal outcome - 'success'
  or 'object_not_found' for handover/placement, 'success' or
  'detection_failed' for detection (see `create_statemachine()` in the
  same file for the exact outcome names).
- grasping_pipeline's own `object_mapping.yaml` uses the same YCB-style
  naming (e.g. "003_cracker_box", "025_mug") already used everywhere in
  this repo, via `_CLASS_TO_OBJECT_NAME` below - no translation needed
  between GraspKG's object_name and grasping_pipeline's object_name.
- grasping_pipeline already depends on and launches `haf_grasping`
  itself (`launch/grasping_pipeline_servers.launch` includes
  `haf_grasping/launch/haf_grasping_all.launch`) as one of its two
  pluggable grasp-point-estimation backends (`grasppoint_estimator_topic`
  in config.yaml). That supersedes `graspkg_ros/haf_grasping_client.py`
  for the main path: grasping_pipeline's own FindGrasp state already does
  detection -> pose estimation -> grasp-point search (via haf_grasping
  when needed) -> MoveIt execution -> placement/handover, end to end.
  There is no more "hand off to grasping_pipeline" TODO because this
  node's job now genuinely ends there - haf_grasping_client.py is kept
  only as a reference for driving haf_grasping directly, bypassing
  grasping_pipeline, if that's ever wanted.

STILL NOT VERIFIED: the `robot_llm` ROS package itself (the one defining
`RobotLLMAction`/`RobotLLMGoal`/`RobotLLMResult`) isn't in either public
repo (grasping_pipeline, grasping_pipeline_msgs) - it must already be on
your workspace's ROS_PACKAGE_PATH since you have the LLM state machine
running, but if `rospack find robot_llm` comes up empty, get it from
wherever the rest of your HSR stack's internal packages live and rebuild.
"""
import json

import actionlib
import rospy

from spatialkg_ros.srv import FindAndGrasp, FindAndGraspResponse, LocateObject

from graspkg_ros.srv import AddDetection, ReportGraspOutcome

try:
    from robot_llm.msg import RobotLLMAction, RobotLLMGoal
    _ROBOT_LLM_IMPORT_OK = True
    _ROBOT_LLM_IMPORT_ERROR = ""
except ImportError as exc:
    _ROBOT_LLM_IMPORT_OK = False
    _ROBOT_LLM_IMPORT_ERROR = str(exc)

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


ROBOT_LLM_ACTION_SERVER = "/robot_llm"


class SpatialToGraspHandoff:
    def __init__(self):
        rospy.init_node("spatialkg_to_graspkg_handoff")

        # If false, this node behaves exactly as before: locate + advise,
        # no execution. Set true once grasping_pipeline's LLM state machine
        # is actually running (see module docstring).
        self.trigger_grasp = rospy.get_param("~trigger_grasp", False)
        self.grasp_task = rospy.get_param("~grasp_task", "handover")  # or "placement"
        self.grasp_timeout = rospy.get_param("~grasp_timeout", 60.0)  # seconds; a real pick is slow

        rospy.wait_for_service("spatialkg_node/locate_object")
        rospy.wait_for_service("graspkg_node/add_detection")
        rospy.wait_for_service("graspkg_node/report_outcome")
        self._locate = rospy.ServiceProxy("spatialkg_node/locate_object", LocateObject)
        self._add_detection = rospy.ServiceProxy("graspkg_node/add_detection", AddDetection)
        self._report_outcome = rospy.ServiceProxy("graspkg_node/report_outcome", ReportGraspOutcome)

        self._robot_llm = None
        if self.trigger_grasp:
            if not _ROBOT_LLM_IMPORT_OK:
                rospy.logerr(
                    "spatialkg_to_graspkg_handoff: ~trigger_grasp is true but "
                    "'robot_llm.msg' isn't importable (%s). Falling back to "
                    "advisory-only mode - fix ROS_PACKAGE_PATH and restart to "
                    "actually execute grasps.", _ROBOT_LLM_IMPORT_ERROR,
                )
                self.trigger_grasp = False
            else:
                self._robot_llm = actionlib.SimpleActionClient(ROBOT_LLM_ACTION_SERVER, RobotLLMAction)
                rospy.loginfo(
                    "spatialkg_to_graspkg_handoff: waiting for %s (start grasping_pipeline with "
                    "use_llm_state_machine:=true if this hangs)...", ROBOT_LLM_ACTION_SERVER,
                )
                self._robot_llm.wait_for_server()
                rospy.loginfo("spatialkg_to_graspkg_handoff: connected to %s", ROBOT_LLM_ACTION_SERVER)

        rospy.Service("~find_and_grasp", FindAndGrasp, self._handle)
        rospy.loginfo(
            "spatialkg_to_graspkg_handoff: ready (trigger_grasp=%s, grasp_task=%s)",
            self.trigger_grasp, self.grasp_task,
        )

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
        # from category, but GraspKG's pose-consistency check may trip
        # it for categories whose stable orientation isn't upright. Extend
        # LiveDetection/RegisterDetection with orientation if PODGE gives
        # you one and this matters for your use case.
        grasp = self._add_detection(
            object_name=object_name,
            confidence=location.confidence if location.confidence >= 0 else 0.5,
            position_x=location.position_x, position_y=location.position_y, position_z=location.position_z,
            quat_x=0.0, quat_y=0.0, quat_z=0.0, quat_w=1.0,
            frame_id="",
        )
        resp.grasp_type = grasp.grasp_type
        resp.consistency_ok = grasp.consistency_ok

        if not self.trigger_grasp:
            resp.success = True
            resp.message = f"{req.query_class} found in {resp.room}; " + grasp.message
            return resp
        if not grasp.consistency_ok:
            resp.success = True
            resp.message = (
                f"{req.query_class} found in {resp.room}, but GraspKG flagged a pose "
                f"inconsistency - not executing a grasp. " + grasp.message
            )
            return resp

        # --- actually execute the pick, via grasping_pipeline's own
        # LLM-facing entry point, not a hand-rolled MoveIt call ---
        goal = RobotLLMGoal(task=self.grasp_task, object_name=object_name)
        rospy.loginfo(
            "spatialkg_to_graspkg_handoff: sending %s goal for %s to %s",
            self.grasp_task, object_name, ROBOT_LLM_ACTION_SERVER,
        )
        self._robot_llm.send_goal(goal)
        finished = self._robot_llm.wait_for_result(rospy.Duration(self.grasp_timeout))
        if not finished:
            resp.success = False
            resp.grasp_executed = True
            resp.grasp_succeeded = False
            resp.message = f"grasping_pipeline timed out executing '{self.grasp_task}' on {object_name}"
            return resp

        result = self._robot_llm.get_result()
        resp.grasp_executed = True
        resp.execution_message = result.result if result is not None else ""

        try:
            userdata = json.loads(result.result)
            status = userdata.get("status")
        except (ValueError, AttributeError, TypeError) as exc:
            rospy.logerr("spatialkg_to_graspkg_handoff: couldn't parse grasping_pipeline result: %s", exc)
            resp.success = False
            resp.message = f"grasping_pipeline returned an unparseable result: {exc}"
            return resp

        # create_statemachine()'s top-level outcomes are 'success' or
        # 'object_not_found' for handover/placement (see module docstring) -
        # anything else is unexpected, so treat it as a failed attempt
        # rather than silently reporting success.
        succeeded = status == "success"
        resp.grasp_succeeded = succeeded

        outcome = self._report_outcome(instance_uri=grasp.instance_uri, succeeded=succeeded)
        resp.success = True
        resp.message = (
            f"{req.query_class} found in {resp.room}; {grasp.message}; "
            f"grasping_pipeline '{self.grasp_task}' {'succeeded' if succeeded else f'ended with status={status!r}'} "
            f"(GraspKG success rate for {grasp.category}/{grasp.grasp_type} now "
            f"{outcome.updated_success_rate:.2f})"
        )
        return resp


if __name__ == "__main__":
    SpatialToGraspHandoff()
    rospy.spin()
