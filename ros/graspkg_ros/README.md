# graspkg_ros

ROS1 Noetic wrapper around the pure-python `graspkg` KG core, for running
GraspKG live against PODGE and the Toyota HSR ("Sasha") in your
`~/HSR/catkin_ws`.

## What changed once real information came in

An earlier version of this package guessed PODGE published a continuous
`vision_msgs/Detection3DArray` topic, then a later version guessed it was
a single combined `object_detector_msgs/get_poses` service. Both were
wrong. The real interface is now confirmed directly from
`grasping_pipeline`'s own source (`src/object_detector.py`,
`src/pose_estimator.py` - the same PODGE this package talks to, since
`grasping_pipeline` calls it too): **two separate actionlib action
servers**, both using `robokudo_msgs/GenericImgProcAnnotatorAction` (a
generic image-processing annotator action type from the RoboKudo project,
University of Bremen) - an object detector (YOLOv8, default topic
`/object_detector/yolov8`) that takes `rgb`/`depth` and returns
`class_names`/`class_confidences`/`bounding_boxes`, then a pose estimator
(GDRNPP, default topic `/pose_estimator/gdrnet`) that takes those results
plus `rgb`/`depth` again and returns `class_names`/`class_confidences`/
`pose_results`. `podge_bridge_node.py`'s `_call_podge()` calls both in
sequence - see the docstring at the top of that file for the full detail.

Separately, your workspace already has a real grasp-execution stack:
`haf_grasping` (public, from the same lab - David Fischinger with Markus
Vincze, TU Wien), and `grasping_pipeline` / `grasping_pipeline_msgs` (also
V4R/TU Wien). `haf_grasping_client.py` calls the *real*, verified
`haf_grasping` action interface directly (fetched from
github.com/davidfischinger/haf_grasping) - GraspKG's job is to bias its
point-cloud grasp search with a semantic approach vector, not to reinvent
arm motion. But `grasping_pipeline` already wraps `haf_grasping`
internally (its `grasping_pipeline_servers.launch` includes
`haf_grasping/launch/haf_grasping_all.launch`), and it's `grasping_pipeline`'s
own `/robot_llm` actionlib action - not a hand-rolled MoveIt call - that
now owns the actual pick/place/handover execution end to end. See
`spatialkg_ros/scripts/spatialkg_to_graspkg_handoff.py`'s docstring for
that hand-off, which is confirmed rather than a guess or a `TODO` now.
`haf_grasping_client.py` in this package is kept only as an optional,
independent way to drive `haf_grasping` directly (e.g. for debugging
grasp-point search in isolation) - nothing in the main path depends on it.

## 1. What's verified vs. what's still a guess

**Verified (safe to rely on):**
- ROS1 Noetic, real catkin workspace at `~/HSR/catkin_ws`.
- `haf_grasping`'s action (`CalcGraspPointsServerAction`, server name
  `calc_grasppoints_svm_action_server`) and its `GraspInput`/`GraspOutput`
  messages, fetched directly from the public repo - `haf_grasping_client.py`
  is built against these exactly, field for field.
- `podge_bridge_node.py`'s `_call_podge()`: the two-actionlib-server
  `robokudo_msgs/GenericImgProcAnnotatorAction` interface described above,
  confirmed from `grasping_pipeline`'s own source rather than from
  `rosservice`/`rostopic` introspection. Default topics
  (`/object_detector/yolov8`, `/pose_estimator/gdrnet`) match
  `grasping_pipeline/config/config.yaml`'s own defaults, and are
  overridable via `~object_detector_topic`/`~pose_estimator_topic` params
  (or the matching `graspkg.launch` args) if yours differ.
- The hand-off from GraspKG's advice to actual execution: `grasping_pipeline`'s
  `/robot_llm` action (`task='handover'|'placement'|'detection'`,
  `object_name=<class>`), triggered from
  `spatialkg_to_graspkg_handoff.py` when `~trigger_grasp:=true`, with the
  result fed back into `graspkg_node/report_outcome`.

**Still worth confirming empirically (not wrong, just unverified from
source alone):**
- Whether PODGE's `class_names` come back as human-readable names (e.g.
  `'025_mug'`) or generic `obj_NNNNNN` IDs when running with
  `dataset: 'ycb_bop'` - `grasping_pipeline/config/object_mapping.yaml`
  has mapping sections for `ycb_ichores` and `hope` but none for
  `ycb_bop`, which suggests the former, but print
  `detection_result.class_names` once running to be sure. If it's IDs,
  add a `ycb_bop` mapping table and translate in `_call_podge()`.
- `haf_grasping_client.py`'s point-cloud topic (`~cloud_topic`, guessed as
  the HSR's raw registered points - `table_plane_extractor`, already in
  your workspace, may already publish a better-segmented object cloud;
  point `~cloud_topic` at that instead if so) and the per-category
  approach-vector table (`TOP_DOWN_GRASP_TYPES` - haf_grasping's own rviz
  visualization, the black arrow, shows you the direction it actually
  used, so this is easy to eyeball and correct). This path is now optional
  (see above), so this only matters if you use it directly.
- The `robot_llm` ROS package itself (which defines `RobotLLMAction`) -
  it's not in `grasping_pipeline`'s own public dependency list, so confirm
  `rospack find robot_llm` resolves on your workspace before relying on
  the `~trigger_grasp:=true` path.

## 2. Build

```bash
# make the pure-python core importable by whatever Python your ROS
# nodes run under:
cd /path/to/graspkg_project
pip install -r requirements.txt
pip install -e .

# drop this folder into your existing workspace and build
cp -r ros/graspkg_ros ~/HSR/catkin_ws/src/
cd ~/HSR/catkin_ws
catkin_make          # or: catkin build
source devel/setup.bash
```

`haf_grasping` needs to already be built in the same workspace (it is,
per your `src/` listing) since `graspkg_ros` depends on its action/message
package at build time.

## 3. Run

```bash
# core KG node + PODGE bridge:
roslaunch graspkg_ros graspkg.launch

# also start the haf_grasping client (optional - only needed if you want
# to drive haf_grasping directly, bypassing grasping_pipeline; only once
# haf_grasping itself and a depth stream are running):
roslaunch graspkg_ros graspkg.launch run_haf_grasping_client:=true

# override the PODGE topics if yours differ from grasping_pipeline's own
# config.yaml defaults:
roslaunch graspkg_ros graspkg.launch \
  object_detector_topic:=/object_detector/yolov8 \
  pose_estimator_topic:=/pose_estimator/gdrnet
```

This assumes PODGE is already up (`xhost local:docker && DATASET=ycbv
CONFIG=params_sasha.yaml docker compose -f docker_compose/gdrnpp_yolov8.yml
up`, in your usual PODGE checkout) and `grasping_pipeline`'s
`config/config.yaml` has `dataset: 'ycb_bop'` set - see `TESTING.md`'s
Phase 7 for the full checklist.

## 4. Try the KG side without PODGE or haf_grasping running

```bash
rosservice call /graspkg_node/add_detection \
  "object_name: '025_mug'
   confidence: 0.91
   position_x: 0.5
   position_y: 0.0
   position_z: 0.8
   quat_x: 0.0
   quat_y: 0.0
   quat_z: 0.0
   quat_w: 1.0
   frame_id: 'head_rgbd_sensor_rgb_frame'"
```

returns `grasp_type: HandleGrasp`, `source: rule`, plus a human-readable
`message`. Report an outcome and watch `known_success_rate` move:

```bash
rosservice call /graspkg_node/report_outcome \
  "instance_uri: '<paste instance_uri from above>'
   succeeded: true"
```

With PODGE actually running, the equivalent one-shot call triggering a
real detection is:

```bash
rosservice call /podge_bridge_node/detect_and_advise "object_name_filter: []"
```

which returns a `GraspAdvice[]` - one entry per object PODGE saw, already
run through GraspKG's rules/embeddings.

## 5. Services, topics and actions

| Name | Type | Direction |
|---|---|---|
| `/graspkg_node/add_detection` | `graspkg_ros/AddDetection` | service - ingest a detection, get advice back |
| `/graspkg_node/get_grasp_advice` | `graspkg_ros/GetGraspAdvice` | service - re-query advice for a known instance |
| `/graspkg_node/report_outcome` | `graspkg_ros/ReportGraspOutcome` | service - feed a real grasp result back into the KG |
| `/graspkg_node/grasp_advice` | `graspkg_ros/GraspAdvice` | topic - published on every `add_detection` call |
| `/podge_bridge_node/detect_and_advise` | `graspkg_ros/DetectAndAdvise` | service - trigger PODGE once, forward everything into the KG |
| `calc_grasppoints_svm_action_server` | `haf_grasping/CalcGraspPointsServerAction` | actionlib - real haf_grasping interface, called by `haf_grasping_client.py` |

## 6. Extending

- **Retraining embeddings live.** `graspkg_node` trains the TransE model
  once at startup. As `report_outcome` accumulates evidence, periodically
  retraining (timer, or a new `~retrain_embeddings` service) would let the
  refinement layer track a growing KG - natural next step for LO8/LO1
  together.
- **Persisting the graph.** `store.serialize(path)` dumps the working
  graph to Turtle; call it in `rospy.on_shutdown` if detection history and
  success-rate statistics should survive a restart.
- **New object classes.** Add the class + category to
  `graspkg/ontology/grasp_ontology.ttl` and `reference_data.py`'s
  `LEAF_TO_CATEGORY` - no code in the reasoning or advisory layers needs to
  change.
- **Real horizontal approach vectors.** `approach_vector_for()` in
  `haf_grasping_client.py` currently returns a fixed world-frame axis for
  side/handle grasps. A tf2 lookup of the object's position in `base_link`,
  normalized in the xy-plane, would give a genuinely robot-relative
  approach direction instead.
