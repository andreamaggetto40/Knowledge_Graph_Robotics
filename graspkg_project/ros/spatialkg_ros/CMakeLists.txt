cmake_minimum_required(VERSION 3.0.2)
project(spatialkg_ros)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  sensor_msgs
  message_generation
)

add_service_files(
  FILES
  RegisterScene.srv
  RegisterDetection.srv
  LocateObject.srv
  ApplyCorrection.srv
  FindAndGrasp.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs sensor_msgs message_runtime
)

include_directories(${catkin_INCLUDE_DIRS})

catkin_install_python(PROGRAMS
  scripts/spatialkg_node.py
  scripts/podge_to_spatialkg_bridge.py
  scripts/spatialkg_to_graspkg_handoff.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
