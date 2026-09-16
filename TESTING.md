# Testing guide

Test in this order. Each phase only needs what the previous phase already
proved works, so a failure always points at something new rather than
something you haven't checked yet. Phases 1-4 need nothing but Python -
do those first, today, regardless of robot access. Phases 5+ need your
real `~/HSR/catkin_ws`.

## Phase 1 - environment

```bash
cd graspkg_project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .        # makes `graspkg` and `spatialkg` importable everywhere
```

If this fails, nothing downstream can work - fix it before moving on.
`rdflib`, `owlrl`, and `numpy` are the only real dependencies; there's
nothing GPU- or ROS-specific here yet.

## Phase 2 - unit tests

```bash
pytest tests/ -v
```

Expect **17 passed** (8 in `test_pipeline.py` for GraspKG, 9 in
`test_spatial_pipeline.py` for SpatialKG). This is the fastest possible
signal something's wrong, so re-run it after *any* change you make,
including ones that look ROS-only - a lot of the actual logic lives in the
plain-Python core, not the node scripts.

If something fails here, don't proceed to the ROS phases - fix it first.
Run a single failing test in isolation for a clearer traceback:

```bash
pytest tests/test_spatial_pipeline.py::test_room_propagation_is_recursive -v
```

## Phase 3 - offline demos (read the output, don't just check the exit code)

```bash
python3 scripts/run_spatial_demo.py
```

Walk through what each section should show:
- `[acquisition]` - loaded 2 scans, 15 object observations, 9 relationships, 7 same-instance links.
- `[reasoning]` - derived 6 new triples (room propagated through support chains), 7 entities flagged stale (the earlier of the two scans, correctly superseded by the later one).
- `[reachability]` - `Kitchen` can reach `Corridor` and `LivingRoom` (2 hops, via the recursive rule).
- `[query service]` - `Mug` should report it moved to the `Shelf` (that's the scripted "someone moved it between scans" scenario); `PowerDrill` should say **no observation and no confident prediction** - this is the correct, desired answer, not a bug. If `PowerDrill` (or anything else absent from the sample scene) ever returns a confident-sounding answer instead of admitting it doesn't know, that's a real regression in the anti-hallucination behavior - worth an immediate look.
- `[evolution]` - after the scripted correction, `MustardBottle` should report `LivingRoom`, with a history note mentioning it was previously seen in `Kitchen`.

```bash
python3 scripts/run_demo.py
```

Same idea for GraspKG: check that every printed grasp recommendation has a
`source` of `rule` (all 12 classes have a category-level rule, so
`embedding` shouldn't appear here - if it does, something in the ontology
broke), and that inconsistent poses get flagged with a `WARNING`.

## Phase 4 - evaluation scripts (the numbers for your report)

```bash
python3 scripts/evaluate_spatial_rules.py     # rule coverage + reachability closure size
python3 scripts/evaluate_spatial_embeddings.py  # leave-one-out link prediction (ComplEx)
python3 scripts/evaluate_rules.py             # same idea, GraspKG
python3 scripts/evaluate_embeddings.py
```

Two things worth knowing going in, so you don't mistake correct-but-modest
results for bugs:
- The spatial ComplEx numbers (mean rank ~4.7 of 8 candidates on the
  sample scene) are unimpressive **because the sample scene is tiny** -
  6 training facts is not enough to learn much from. That's an honest,
  reportable finding (embeddings need volume; rules don't), not something
  to "fix" - it should improve substantially once you load real
  3RScan/3DSSG data with `scene_loader.load_scene_file` instead of the
  sample. These numbers are now deterministic run-to-run for a fixed seed
  (an earlier version of `fit()` shuffled training order with Python's
  unseeded global `random` module instead of the seeded numpy generator -
  fixed, so a given seed now reproduces the same numbers every time).
- GraspKG's `recommendedGraspType` relation is a clean one-to-one mapping
  in that ontology, so its own leave-one-out numbers are close to random
  by design (see the docstring in `evaluate_embeddings.py`) - only
  `hasAffordance` (shared across categories) should show real lift.

**Try this yourself:** edit `spatialkg/sample_data/sample_scene.json` to
add a third scan, a new room, or a new object placement, then re-run
`run_spatial_demo.py` and the two spatial scripts. If the counts/behaviour
change the way you'd expect from your edit, the pipeline is doing what it
says. This is the cheapest way to build confidence in the logic before
touching ROS at all.

## Phase 5 - catkin build (still no robot needed)

```bash
cp -r ros/graspkg_ros ros/spatialkg_ros ~/HSR/catkin_ws/src/
cd ~/HSR/catkin_ws
catkin_make        # or: catkin build
source devel/setup.bash
```

If the workspace is large and slow, isolate build errors to just the new
packages:

```bash
catkin_make --pkg graspkg_ros spatialkg_ros
```

Likely failure modes and what they mean:
- **`haf_grasping` not found** - `graspkg_ros` depends on it at build time (for its action/message types). It needs to already be built in the same workspace, which your `src/` listing suggests it is - if the build still can't find it, check it's actually been `catkin_make`'d at least once itself.
- **`vision_msgs`/`object_detector_msgs` errors** - shouldn't happen; neither package's `package.xml` declares `object_detector_msgs` as a dependency yet, deliberately, since I haven't confirmed it's needed there (see Phase 7). If you see this, something's referencing it that shouldn't be yet.
- **Python import errors when a node actually runs** (not at build time) - almost always means `pip install -e .` (Phase 1) wasn't done in the Python environment your ROS nodes actually run under. `roscore`/`rosrun` use whatever `python3` is on `PATH` at launch time, which may not be your venv - either activate the venv before `roslaunch`, or `pip install -e .` outside the venv too.

## Phase 6 - ROS smoke test, no PODGE, no robot

This is the most important phase for trusting the rest: it proves the
services, message types, and node wiring are structurally correct,
completely independent of the two things I couldn't verify (PODGE's real
interface, sasha_gpt's interface).

```bash
roslaunch spatialkg_ros spatialkg.launch
```

In another terminal, once you see `spatialkg_node: ready (... triples loaded)`:

```bash
rosservice list | grep -E "spatialkg|graspkg"

rosservice call /spatialkg_node/locate_object "query_class: 'Mug'"
# expect: found=True, room='Kitchen', support_chain=['Mug','Shelf','Kitchen'], source='observation'

rosservice call /spatialkg_node/locate_object "query_class: 'PowerDrill'"
# expect: found=False, source='none' - the honest "I don't know" case

rosservice call /spatialkg_node/apply_correction \
  "query_class: 'MustardBottle'
   correct_room_id: 'LivingRoom'
   corrected_by: 'user'"
rosservice call /spatialkg_node/locate_object "query_class: 'MustardBottle'"
# expect: room now 'LivingRoom', history_note mentioning Kitchen
```

Then bring up GraspKG the same way and test it in isolation
(`ros/graspkg_ros/README.md` has the exact `add_detection`/`report_outcome`
calls), before testing the two together:

```bash
roslaunch spatialkg_ros spatialkg.launch bring_up_graspkg:=true run_graspkg_handoff:=true
# in another terminal:
rosservice call /spatialkg_to_graspkg_handoff/find_and_grasp "query_class: 'Mug'"
# expect: found=True, room='Kitchen', grasp_type='HandleGrasp', consistency_ok depends on the identity-quaternion caveat noted in spatialkg_ros/README.md
```

If every call in this phase behaves as expected, the entire KG logic and
ROS plumbing is verified end to end - anything that goes wrong from here
on is isolated to the two integration points below, not to this core.

## Phase 7 - real PODGE

Confirm the real interface first (see `graspkg_ros/README.md`'s checklist
- `rosservice list`/`type`, and `find ... -name "*.srv"` on
`object_detector_msgs`), then fix `_call_podge()` in **both**
`graspkg_ros/scripts/podge_bridge_node.py` and
`spatialkg_ros/scripts/podge_to_spatialkg_bridge.py` (they duplicate the
same guessed function). Re-run the Phase 6 calls afterwards, but this time
by triggering a real detection instead of calling the KG services by hand:

```bash
rosservice call /podge_bridge_node/detect_and_advise "object_name_filter: []"
# or watch it happen automatically:
rostopic echo /graspkg_node/grasp_advice
```

## Phase 8 - haf_grasping

Confirm `haf_grasping` itself is alive independent of my code first (its
own example client, or `roslaunch haf_grasping haf_grasping_all.launch` +
its rviz visualization), then run `haf_grasping_client.py` and check the
black arrow in rviz matches the approach direction you'd expect for the
grasp type being requested - that's the direct way to sanity-check the
`TOP_DOWN_GRASP_TYPES` table's assumption without needing to read code.

## Phase 9 - full loop

PODGE sighting -> SpatialKG locates it -> (optionally) a correction ->
hand-off to GraspKG -> `haf_grasping` -> your existing
`grasping_pipeline`/`hsrb_moveit` -> outcome reported back. The last arrow
in that chain is still an open `TODO` in `haf_grasping_client.py` until
`grasping_pipeline_msgs`'s interface is confirmed - everything before it
should already work by this point.

## Debugging tips

- **Inspect the graph directly** rather than guessing why a query returned
  nothing: `store.serialize("/tmp/debug.ttl")` from a Python shell, then
  read the Turtle file, or run ad-hoc SPARQL via `store.select(...)`.
- **A gotcha I hit myself, in case you extend the ontology and hit it too:**
  this rdflib version doesn't match a string literal stored with an
  explicit `datatype=XSD.string` against a bare `"..."` in a SPARQL triple
  pattern - store plain `Literal(value)` (no datatype) for anything you
  intend to filter on directly in a query, or use
  `FILTER(str(?x) = "...")` instead.
- **Two open unknowns, not bugs:** if PODGE- or sasha_gpt-related pieces
  don't work, that's expected until Phase 7/the sasha_gpt wiring is
  confirmed - re-check Phase 6 still passes to confirm the core itself
  isn't at fault.
- **Another gotcha already fixed, in case you add your own randomized
  training/sampling code:** always draw randomness from the seeded numpy
  generator (`self._rng`) inside a class that takes a `seed` parameter,
  never from Python's global `random` module - the latter isn't
  reproducible run-to-run even with a fixed seed elsewhere, which is
  exactly what caused the embeddings numbers above to drift before it was
  fixed.
