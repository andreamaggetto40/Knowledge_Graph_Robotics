cmake_minimum_required(VERSION 3.0.2)
project(graspkg_ros)

find_package(catkin REQUIRED COMPONENTS
  rospy
  actionlib
  std_msgs
  sensor_msgs
  geometry_msgs
  haf_grasping
  message_generation
)

add_message_files(
  FILES
  GraspAdvice.msg
)

add_service_files(
  FILES
  AddDetection.srv
  GetGraspAdvice.srv
  ReportGraspOutcome.srv
  DetectAndAdvise.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
  geometry_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy actionlib std_msgs sensor_msgs geometry_msgs haf_grasping message_runtime
)

include_directories(${catkin_INCLUDE_DIRS})

catkin_install_python(PROGRAMS
  scripts/graspkg_node.py
  scripts/podge_bridge_node.py
  scripts/haf_grasping_client.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
