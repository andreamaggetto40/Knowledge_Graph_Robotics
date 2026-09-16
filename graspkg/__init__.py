"""GraspKG - a perception-grounded, affordance-aware knowledge graph for
explainable grasp reasoning on the Toyota HSR.

This package is pure Python (rdflib + owlrl + numpy) and knows nothing about
ROS - it can be developed, tested and evaluated completely offline using
`detectors.SimulatedPODGEStream`. The `ros/graspkg_ros` catkin package
wraps this library in ROS nodes for use on the real robot.
"""

__version__ = "0.1.0"
