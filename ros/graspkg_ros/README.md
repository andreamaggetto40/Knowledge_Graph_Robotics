# graspkg_ros

ROS1 Noetic wrapper around the pure-python `graspkg` KG core, for running
GraspKG live against PODGE and the Toyota HSR ("Sasha") in your
`~/HSR/catkin_ws`.

## What changed once real information came in

An earlier version of this package assumed PODGE published a continuous
`vision_msgs/Detection3DArray` topic. Your actual container logs show
YOLOv8 and GDRNPP both run as **request/response services**
("Server started, waiting for requests...", "Pose Estimation with GDRNPP
is ready.") under what looks like a `/pose_estimator/...` namespace, using
`object_detector_msgs` types. `podge_bridge_node.py` is now a **service
client**, not a topic subscriber - but I still don't have the exact
service name or field names, so that one function is a clearly marked,
best-effort guess (see below).

Separately, your workspace already has a real grasp-execution stack:
`haf_grasping` (public, from the same lab - David Fischinger with Markus
Vincze, TU Wien), `grasping_pipeline` / `grasping_pipeline_msgs`, and
`hsrb_moveit`. `haf_grasping_client.py` calls the *real*, verified
`haf_grasping` action interface (fetched from
github.com/davidfischinger/haf_grasping) - GraspKG's job is to bias its
point-cloud grasp search with a semantic approach vector, not to reinvent
arm motion. `grasping_pipeline` / `hsrb_moveit` still own the actual pick
execution; I don't have `grasping_pipeline_msgs`'s contents yet, so that
final hand-off is a marked `TODO` rather than a guess.

## 1. What's verified vs. what's still a guess

**Verified (safe to rely on):**
- ROS1 Noetic, real catkin workspace at `~/HSR/catkin_ws`.
- `haf_grasping`'s action (`CalcGraspPointsServerAction`, server name
  `calc_grasppoints_svm_action_server`) and its `GraspInput`/`GraspOutput`
  messages, fetched directly from the public repo - `haf_grasping_client.py`
  is built against these exactly, field for field.

**Still a guess - check before relying on it:**
- `podge_bridge_node.py`'s `_call_podge()`: the service name
  (`/pose_estimator/get_poses`, param `~podge_service`) and the
  `object_detector_msgs` request/response shape (`get_poses` /
  `get_posesRequest`, fields `.name` / `.confidence` / `.pose` on each
  result). Confirm with:

  ```bash
  rosservice list | grep -iE "pose_estimator|yolo|gdrn"
  rosservice type <the name that shows up>
  find ~/HSR/catkin_ws/src/object_detector_msgs -name "*.srv" -o -name "*.msg" \
      | xargs -I{} sh -c 'echo === {} ===; cat {}'
  ```

  Only `_call_podge()` needs to change once you know the real answer -
  everything else in that file (forwarding into `graspkg_node`, the
  `~detect_and_advise` service shape) is independent of it.
- `haf_grasping_client.py`'s point-cloud topic (`~cloud_topic`, guessed as
  the HSR's raw registered points - `table_plane_extractor`, already in
  your workspace, may already publish a better-segmented object cloud;
  point `~cloud_topic` at that instead if so) and the per-category
  approach-vector table (`TOP_DOWN_GRASP_TYPES` - haf_grasping's own rviz
  visualization, the black arrow, shows you the direction it actually
  used, so this is easy to eyeball and correct).
- The final hand-off from a `haf_grasping` result to `grasping_pipeline`/
  `hsrb_moveit` and back into `graspkg_node/report_outcome` - marked
  `TODO` at the bottom of `haf_grasping_client.py`. Tell me how
  `grasping_pipeline` wants to be called (service? actionlib? - check
  `grasping_pipeline_msgs`) and I'll wire it up for real.

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

# also start the haf_grasping client (only once haf_grasping itself and a
# depth stream are running):
roslaunch graspkg_ros graspkg.launch run_haf_grasping_client:=true

# override the guessed PODGE service / topics if needed:
roslaunch graspkg_ros graspkg.launch podge_service:=/your/real/service
```

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

Once PODGE's real service is confirmed, the equivalent one-shot call is:

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
