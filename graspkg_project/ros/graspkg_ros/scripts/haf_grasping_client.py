#!/usr/bin/env python3
"""haf_grasping_client: turns GraspKG's semantic advice into a real call to
haf_grasping (David Fischinger / Vincze, TU Wien - the same haf_grasping
already in your workspace), biasing its point-cloud grasp search with the
category-appropriate approach direction instead of leaving it at the
default straight-down search.

This one IS verified against the real, public haf_grasping interface
(github.com/davidfischinger/haf_grasping: action/CalcGraspPointsServer.action,
msg/GraspInput.msg, msg/GraspOutput.msg) - not a guess.

What this script does NOT do: move the arm. haf_grasping only returns
candidate grasp points; turning that into a real pick belongs to your
existing grasping_pipeline / hsrb_moveit stack. Once you tell me how
grasping_pipeline wants to be called, the marked TODO at the bottom is
where that hand-off (and the ReportGraspOutcome call back into GraspKG)
goes.
"""
import actionlib
import rospy
from geometry_msgs.msg import Point, Vector3
from sensor_msgs.msg import PointCloud2

from haf_grasping.msg import CalcGraspPointsServerAction, CalcGraspPointsServerGoal, GraspInput
from graspkg_ros.msg import GraspAdvice

HAF_ACTION_SERVER = "calc_grasppoints_svm_action_server"

# Starting point only - haf_grasping's own rviz visualization (the black
# arrow) shows you the approach direction it actually used, so verify and
# adjust per category. "Top-down" categories get approach_vector (0,0,1);
# everything else gets a horizontal default (1,0,0). A better version would
# look up the object's position in base_link via tf2 and point horizontally
# from the robot toward the object instead of a fixed world axis - worth
# doing once the rest of the pipeline is confirmed working.
TOP_DOWN_GRASP_TYPES = {"BoxPrecisionGrasp", "RimGrasp"}


def approach_vector_for(grasp_type: str) -> Vector3:
    if grasp_type in TOP_DOWN_GRASP_TYPES:
        return Vector3(0.0, 0.0, 1.0)
    return Vector3(1.0, 0.0, 0.0)  # SideCylindricalGrasp, HandleGrasp, ElongatedSideGrasp, ToolHandleGrasp


class HAFGraspingClient:
    def __init__(self):
        rospy.init_node("haf_grasping_client")

        # GUESS: point cloud topic. table_plane_extractor is already in your
        # workspace and likely publishes the object cloud haf_grasping wants
        # (segmented from the table plane) - point this at its real output
        # topic if it differs from the HSR's raw registered points.
        self.cloud_topic = rospy.get_param(
            "~cloud_topic", "/hsrb/head_rgbd_sensor/depth_registered/rectified_points"
        )
        self.goal_frame_id = rospy.get_param("~goal_frame_id", "base_link")
        self.grasp_area_size = rospy.get_param("~grasp_area_size", 0.15)  # metres
        self.max_calc_time = rospy.get_param("~max_calc_time", 5.0)  # seconds

        self._client = actionlib.SimpleActionClient(HAF_ACTION_SERVER, CalcGraspPointsServerAction)
        rospy.loginfo("haf_grasping_client: waiting for %s...", HAF_ACTION_SERVER)
        self._client.wait_for_server()
        rospy.loginfo("haf_grasping_client: connected to %s", HAF_ACTION_SERVER)

        rospy.Subscriber("graspkg_node/grasp_advice", GraspAdvice, self._on_advice)

    def _on_advice(self, advice: GraspAdvice):
        if not advice.grasp_type:
            rospy.logwarn("haf_grasping_client: no grasp type for %s, skipping", advice.instance_uri)
            return
        if not advice.consistency_ok:
            rospy.logwarn("haf_grasping_client: pose inconsistency flagged for %s, skipping", advice.instance_uri)
            return

        try:
            cloud = rospy.wait_for_message(self.cloud_topic, PointCloud2, timeout=5.0)
        except rospy.ROSException:
            rospy.logerr("haf_grasping_client: no point cloud on %s within timeout", self.cloud_topic)
            return

        goal = CalcGraspPointsServerGoal()
        goal.graspinput = GraspInput(
            input_pc=cloud,
            goal_frame_id=self.goal_frame_id,
            grasp_area_center=Point(advice.position_x, advice.position_y, advice.position_z),
            grasp_area_length_x=self.grasp_area_size,
            grasp_area_length_y=self.grasp_area_size,
            max_calculation_time=rospy.Duration(self.max_calc_time),
            show_only_best_grasp=True,
            threshold_grasp_evaluation=0,
            approach_vector=approach_vector_for(advice.grasp_type),
            gripper_opening_width=1,
        )

        rospy.loginfo(
            "haf_grasping_client: requesting grasp for %s (%s, %s)",
            advice.instance_uri, advice.category, advice.grasp_type,
        )
        self._client.send_goal(goal)
        finished = self._client.wait_for_result(rospy.Duration(self.max_calc_time + 10.0))
        if not finished:
            rospy.logerr("haf_grasping_client: timed out waiting for a grasp point")
            return

        result = self._client.get_result()
        out = result.graspOutput
        rospy.loginfo(
            "haf_grasping_client: grasp point (%.3f, %.3f, %.3f), approach (%.2f, %.2f, %.2f), roll=%.2f, eval=%d",
            out.averagedGraspPoint.x, out.averagedGraspPoint.y, out.averagedGraspPoint.z,
            out.approachVector.x, out.approachVector.y, out.approachVector.z,
            out.roll, out.eval,
        )

        # TODO once grasping_pipeline_msgs is confirmed: hand `out` (the grasp
        # point + roll + approach vector) to your existing grasping_pipeline /
        # hsrb_moveit stack to actually execute the pick, then call
        # graspkg_node/report_outcome with the real result:
        #
        #   from graspkg_ros.srv import ReportGraspOutcome
        #   report = rospy.ServiceProxy("graspkg_node/report_outcome", ReportGraspOutcome)
        #   report(instance_uri=advice.instance_uri, succeeded=<real pick result>)


if __name__ == "__main__":
    HAFGraspingClient()
    rospy.spin()
