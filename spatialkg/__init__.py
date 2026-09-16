"""SpatialKG - an explainable spatial knowledge graph for the Toyota HSR:
a perception-to-graph layer (g), recursive spatial/reachability rules
(l, r), and KG-embedding-based refinement for occluded objects, serving as
a "System of Record" that an LLM interface (sasha_gpt) queries instead of
guessing.

Pure Python (rdflib + owlrl + numpy), no ROS - develop and test here with
`sample_data/sample_scene.json` before touching the robot. See
`graspkg/` for the companion (secondary) grasp-affordance KG, and
`ros/spatialkg_ros` for the live ROS integration.
"""

__version__ = "0.1.0"
