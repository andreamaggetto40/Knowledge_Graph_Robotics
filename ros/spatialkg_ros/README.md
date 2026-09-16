# spatialkg_ros

ROS1 Noetic wrapper around the pure-python `spatialkg` KG core - the
primary deliverable (the one-pager's "Explainable Spatial Knowledge Graphs
for Deterministic Robotic Action"). `graspkg_ros` is the secondary
grasping extension, linked in via `spatialkg_to_graspkg_handoff.py`.

## What's verified vs. still a guess

Same honesty split as `graspkg_ros/README.md`, because the underlying
uncertainty is identical (I still don't have PODGE's real service
definition):

**Verified:** the pure-python `spatialkg` core (ontology, recursive rules,
ComplEx embeddings, query service) - fully tested, see `../../tests/` and
`../../scripts/run_spatial_demo.py`.

**Also verified, newly:** `spatialkg_to_graspkg_handoff.py`'s
`~trigger_grasp:=true` path, which calls grasping_pipeline's `/robot_llm`
action to actually execute a grasp. Confirmed by reading
grasping_pipeline's own source (github.com/v4r-tuwien/grasping_pipeline -
`src/statemachine_llm.py`, `launch/grasping_pipeline_statemachine.launch`),
not guessed - see that script's docstring for exactly what was checked.
Per your confirmation, grasping_pipeline is already running correctly on
the real robot, so this is the one integration point in this whole repo
that's verified *and* already working end to end, not just verified in
isolation.

**Still a guess:**
- `podge_to_spatialkg_bridge.py`'s `_call_podge()` - identical guessed
  interface to `graspkg_ros/podge_bridge_node.py`'s, duplicated because the
  two catkin packages are independent. Fix both copies once confirmed (see
  `graspkg_ros/README.md`'s checklist for the exact commands to run).
- `podge_to_spatialkg_bridge.py`'s `~room_id` - which room the robot is
  currently in is a fixed param here, not derived from localization. Wire
  it to AMCL pose + a room-containment polygon once that matters.
- `spatialkg_to_graspkg_handoff.py` passes an identity quaternion to
  GraspKG (SpatialKG tracks position, not orientation) - fine for grasp
  *type* selection, but may trip GraspKG's pose-consistency check for
  categories whose stable orientation isn't upright.
- The `robot_llm` ROS package itself (defines `RobotLLMAction`) isn't in
  either public grasping_pipeline repo - confirm `rospack find robot_llm`
  resolves on your workspace before relying on `~trigger_grasp:=true`.

## Build

```bash
cd /path/to/graspkg_project
pip install -r requirements.txt
pip install -e .        # makes both `graspkg` and `spatialkg` importable

cp -r ros/spatialkg_ros ~/HSR/catkin_ws/src/
# graspkg_ros must also be present if you want the hand-off node
cd ~/HSR/catkin_ws && catkin_make && source devel/setup.bash
```

## Run

```bash
# spatial KG alone, loaded with the bundled sample scene:
roslaunch spatialkg_ros spatialkg.launch

# also bring up GraspKG and the hand-off between them:
roslaunch spatialkg_ros spatialkg.launch bring_up_graspkg:=true run_graspkg_handoff:=true

# point at a real 3RScan/3DSSG-format scene once you have one:
roslaunch spatialkg_ros spatialkg.launch scene_file:=/path/to/real_scene.json
```

## Try it without PODGE or the robot

```bash
rosservice call /spatialkg_node/locate_object "query_class: 'Mug'"
```

returns `found: True`, `room: 'Kitchen'`, `support_chain: ['Mug','Shelf','Kitchen']`,
plus `is_stale`/`source`/`explanation` - this is exactly what sasha_gpt
should call before answering "where is the mug" instead of guessing.

Apply a correction and re-query to see it take effect:

```bash
rosservice call /spatialkg_node/apply_correction \
  "query_class: 'MustardBottle'
   correct_room_id: 'LivingRoom'
   corrected_by: 'user'"
rosservice call /spatialkg_node/locate_object "query_class: 'MustardBottle'"
```

Try the secondary extension end to end (needs `bring_up_graspkg:=true run_graspkg_handoff:=true`):

```bash
rosservice call /spatialkg_to_graspkg_handoff/find_and_grasp "query_class: 'Mug'"
```

To also actually execute the grasp (needs grasping_pipeline already
running with `use_llm_state_machine:=true` - see `../../TESTING.md`
Phase 8), add `trigger_grasp:=true` when launching:

```bash
roslaunch spatialkg_ros spatialkg.launch bring_up_graspkg:=true run_graspkg_handoff:=true \
  trigger_grasp:=true grasp_task:=handover

rosservice call /spatialkg_to_graspkg_handoff/find_and_grasp "query_class: 'Mug'"
# now also returns grasp_executed=True, grasp_succeeded reflecting the
# real outcome, and execution_message with grasping_pipeline's raw result
```

## Wiring into sasha_gpt

I don't have sasha_gpt's actual interface, so two starting points, pick
whichever fits once you look:

1. **If sasha_gpt is a ROS node**, it can call `/spatialkg_node/locate_object`
   directly like any other ROS client - no translation needed.
2. **If sasha_gpt does LLM function-calling** (OpenAI/Anthropic-style tool
   use), register `locate_object` as a tool with this schema and have the
   handler call the ROS service underneath:

   ```json
   {
     "name": "locate_object",
     "description": "Look up the most recently confirmed location of an object the robot has seen. Returns whether it was found, which room, staleness, and an explanation - use this instead of guessing a location.",
     "parameters": {
       "type": "object",
       "properties": {
         "query_class": {"type": "string", "description": "Object class name, e.g. 'Mug', 'MustardBottle'"}
       },
       "required": ["query_class"]
     }
   }
   ```

   Share sasha_gpt's actual code/README and I'll write the real glue
   instead of this generic starting point.

## Services

| Name | Type |
|---|---|
| `/spatialkg_node/register_scene` | `spatialkg_ros/RegisterScene` |
| `/spatialkg_node/register_detection` | `spatialkg_ros/RegisterDetection` |
| `/spatialkg_node/locate_object` | `spatialkg_ros/LocateObject` |
| `/spatialkg_node/apply_correction` | `spatialkg_ros/ApplyCorrection` |
| `/spatialkg_to_graspkg_handoff/find_and_grasp` | `spatialkg_ros/FindAndGrasp` |
