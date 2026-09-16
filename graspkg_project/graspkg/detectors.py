"""Adapters that turn perception output into GraspKG Detection objects.

GraspKG never talks to YOLOv8/GDRNPP directly - everything downstream
(graph_creation, reasoning, embeddings, feedback, and the ROS node in
ros/graspkg_ros) only ever depends on the plain `Detection` dataclass below,
never on how it was produced. Two sources are provided here for offline
work; the real ROS integration lives in ros/graspkg_ros/scripts and builds
`Detection` objects the same way.

- SimulatedPODGEStream: generates synthetic detections for the 12
  configured YCB-V classes, for development and the course evaluation,
  without a robot, a GPU, or the docker containers running.
- PODGEAdapter: reads logged detections from a JSONL file (one JSON object
  per line) - a convenient way to replay a real session offline.
"""
from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .reference_data import LEAF_TO_CATEGORY, STABLE_ORIENTATIONS_BY_CATEGORY

# The 12 objects PODGE is configured for (docker_compose/gdrnpp_yolov8.yml,
# CONFIG=params_sasha.yaml, DATASET=ycbv), mapped to GraspKG ontology classes.
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


@dataclass
class Detection:
    """One detection: a YOLOv8 class label + GDRNPP 6D pose."""

    object_name: str  # e.g. "025_mug" - a YCBV_CLASS_MAP key
    confidence: float  # detection confidence, 0-1
    position: tuple  # (x, y, z) in metres, in `frame_id`
    orientation: tuple  # quaternion (x, y, z, w)
    timestamp: float = field(default_factory=time.time)
    frame_id: str = "head_rgbd_sensor_rgb_frame"


class PODGEAdapter:
    """Reads logged detections, one JSON object per line, e.g.:
    {"object": "025_mug", "confidence": 0.91, "position": [0.5,0.0,0.8],
     "orientation": [0,0,0,1], "timestamp": 1737000000.0}

    Handy for replaying a recorded session offline. On the real robot,
    ros/graspkg_ros/scripts/podge_bridge_node.py builds Detection objects
    directly from a ROS topic instead of a file - same dataclass either way.
    """

    def __init__(self, source_path):
        self.source_path = Path(source_path)

    def stream(self) -> Iterator[Detection]:
        with self.source_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield self._read_one(json.loads(line))

    @staticmethod
    def _read_one(record: dict) -> Detection:
        return Detection(
            object_name=record["object"],
            confidence=float(record["confidence"]),
            position=tuple(record["position"]),
            orientation=tuple(record["orientation"]),
            timestamp=record.get("timestamp", time.time()),
            frame_id=record.get("frame_id", "head_rgbd_sensor_rgb_frame"),
        )


class SimulatedPODGEStream:
    """Generates synthetic but bounded-realistic detections for the 12
    configured classes, so the rest of the pipeline can be built and
    evaluated before/without the physical HSR."""

    def __init__(self, seed: int = 0, unstable_pose_rate: float = 0.15):
        self._rng = random.Random(seed)
        self.unstable_pose_rate = unstable_pose_rate

    def sample(self, n: int) -> list:
        return [self._one() for _ in range(n)]

    def _one(self) -> Detection:
        name = self._rng.choice(list(YCBV_CLASS_MAP))
        confidence = round(self._rng.uniform(0.55, 0.98), 3)
        position = (
            round(self._rng.uniform(0.3, 0.9), 3),
            round(self._rng.uniform(-0.3, 0.3), 3),
            round(self._rng.uniform(0.7, 0.9), 3),
        )
        if self._rng.random() < self.unstable_pose_rate:
            orientation = tuple(round(self._rng.uniform(-1, 1), 3) for _ in range(4))
            norm = math.sqrt(sum(c * c for c in orientation)) or 1.0
            orientation = tuple(c / norm for c in orientation)
        else:
            # pick a pose that is actually stable *for this object's category*,
            # so the consistency check in reasoning.py agrees with the simulator
            class_name = YCBV_CLASS_MAP[name]
            category = LEAF_TO_CATEGORY[class_name]
            orientation = self._rng.choice(STABLE_ORIENTATIONS_BY_CATEGORY[category])
        return Detection(name, confidence, position, orientation)
