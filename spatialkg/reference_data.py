"""Shared reference data for SpatialKG.

LEAF_TO_CLASS_URI mirrors graspkg/reference_data.py's LEAF_TO_CATEGORY - the
12 PODGE/YCB-V classes are the same physical objects in both KGs, just
organised under a different top-level hierarchy (grasp affordance category
vs. spatial/portable-object class). Keep the class *names* in sync if you
edit either ontology; that's what lets the GraspKG hand-off
(spatialkg_to_graspkg_handoff.py) pass a leaf class name straight through
without translation.
"""

YCBV_LEAF_CLASSES = [
    "MasterChefCan",
    "CrackerBox",
    "TomatoSoupCan",
    "MustardBottle",
    "GelatinBox",
    "PottedMeatCan",
    "Banana",
    "BleachCleanser",
    "Bowl",
    "Mug",
    "PowerDrill",
    "FoamBrick",
]

# object_name (as PODGE/detectors.YCBV_CLASS_MAP keys) -> ontology leaf class
YCBV_CLASS_MAP = {
    "002_master_chef_can": "MasterChefCan",
    "003_cracker_box": "CrackerBox",
    "005_tomato_soup_can": "TomatoSoupCan",
    "006_mustard_bottle": "MustardBottle",
    "009_gelatin_box": "GelatinBox",
    "010_potted_meat_can": "PottedMeatCan",
    "011_banana": "Banana",
    "021_bleach_cleanser": "BleachCleanser",
    "024_bowl": "Bowl",
    "025_mug": "Mug",
    "035_power_drill": "PowerDrill",
    "061_foam_brick": "FoamBrick",
}

FURNITURE_CLASSES = ["Table", "Cabinet", "Shelf", "Counter"]

# How stale an observation can get before reasoning.check_staleness flags it
# for re-verification instead of being trusted outright (LO8-adjacent: this
# is what stops the KG itself from silently going stale and becoming a new
# source of hallucination).
DEFAULT_STALENESS_THRESHOLD_SECONDS = 6 * 3600  # 6 hours
