"""Shared reference data used by both the simulator (detectors.py) and the
consistency checker (reasoning.py), so 'what counts as a stable pose for
this category' is defined exactly once instead of drifting apart in two
places.
"""

# Leaf class -> top-level category, mirroring ontology/grasp_ontology.ttl's
# rdfs:subClassOf structure. Keep these two in sync if you edit the TTL.
LEAF_TO_CATEGORY = {
    "MasterChefCan": "CylindricalGraspable",
    "CrackerBox": "BoxGraspable",
    "TomatoSoupCan": "CylindricalGraspable",
    "MustardBottle": "CylindricalGraspable",
    "GelatinBox": "BoxGraspable",
    "PottedMeatCan": "BoxGraspable",
    "Banana": "ElongatedGraspable",
    "BleachCleanser": "HandleGraspable",
    "Bowl": "Container",
    "Mug": "HandleGraspable",
    "PowerDrill": "ToolGraspable",
    "FoamBrick": "BoxGraspable",
}

UPRIGHT = (0.0, 0.0, 0.0, 1.0)
ON_SIDE = (0.7071, 0.0, 0.0, 0.7071)

# Reference "stable" resting orientations per top-level category. A real
# system would derive these from the object mesh; here they stand in for
# whatever GDRNPP / a mesh library would supply.
STABLE_ORIENTATIONS_BY_CATEGORY = {
    "CylindricalGraspable": [UPRIGHT, ON_SIDE],
    "BoxGraspable": [UPRIGHT],
    "HandleGraspable": [UPRIGHT],
    "Container": [UPRIGHT],
    "ElongatedGraspable": [ON_SIDE],
    "ToolGraspable": [UPRIGHT, ON_SIDE],
}
