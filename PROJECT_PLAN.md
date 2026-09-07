# Project plan

What is built, what is next, and everything that cannot be answered from this
laptop. The panel itself is described in [README.md](README.md).

## Where it stands

Phase 0 is complete and runnable. Everything in it was built against invented
sensors and stand-in scripts, so the shape is settled but none of it has touched
the car yet. Phase 1 is the part that needs the car, and most of it is small
once the answers in "Open questions" exist.

---

## Phase 0: the panel, off the car (done)

- [x] Project scaffold: uv, ruff, mypy strict, pytest, package under `src/codriver`
- [x] Sensor registry: 8 cameras, 7 lidars, GNSS, with expected rates and which
      ones are allowed to fail
- [x] Config file so topics, script paths and launch commands are edited on the
      car rather than in the code, with `--dump-config` to start from
- [x] Rate backends: `rclpy` live probe, `bag`, `ros2cli`, `mock`, behind one
      interface, chosen by config or `--backend`
- [x] Process manager: start, watch, stop with SIGINT to the process group,
      readiness detection, crash detection, exclusive groups
- [x] Zero-dependency HTTP server: static frontend and JSON API on one port
- [x] Frontend: fixed-width rails around a fluid centre, six vertical tabs,
      right rail split into the same six rows
- [x] Status tab: GNSS, cameras, lidar and the operating-mode commands, stacked
      down the page for the portrait screen in the car
- [x] Recording / RViz tab: split 70 / 30, each greying the other out
- [x] Recording topic switches: per sensor, per column, per criticality, with
      the resolved topic list passed to the recording script
- [x] Perception tab: three pipelines, blue / orange / green / red
- [x] Map, Prediction, Planning placeholders that say they are placeholders
- [x] Log viewer per process, live while the modal is open
- [x] Per-tab notes in `instructions/`, one `<tab-id>.md` each, opened by the
      right-hand rail and read from the repo on every request
- [x] Demo config plus stand-in scripts, so the panel can be driven on a laptop
- [x] 57 tests, ruff clean, mypy strict clean

## Phase 1: make it true on the car (next)

Ordered so that each step is testable on its own.

- [ ] **1.1** Capture `ros2 topic list` and `ros2 topic info -v` for every sensor
      on the car. Paste into the config. This is the single biggest source of
      wrongness right now: every topic name in the defaults is a guess.
- [ ] **1.2** Confirm the script names in `~/scripts/` match what the config
      expects, and make `start_recording.sh` forward `"$@"` to `ros2 bag record`.
      Check each script runs from the panel's environment, not just from an
      interactive shell (PATH and ROS variables differ).
- [ ] **1.3** Run the `rclpy` probe on the car with all sensors up. Confirm it
      reports 20 Hz for cameras and 10 Hz for lidar rather than the low numbers
      `ros2 topic hz` gives.
- [ ] **1.4** Cross-check: record a 2 minute bag by hand, run the `bag` backend
      over the same period, and compare it against the `rclpy` numbers. If they
      agree, the live probe is trustworthy and the status tab can be believed.
      If they disagree, the bag is right and the probe needs the QoS handling
      looked at.
- [ ] **1.5** Restart the car computer, open the panel before touching the GNSS,
      and confirm the top box is red at 1 Hz. Then set it and confirm the box
      goes green. This is the fault the panel exists to catch, and a restart is
      the only way to see it.
- [ ] **1.6** Take each pipeline's real startup output and set `ready_pattern`
      per pipeline, so orange turns green at the right moment. Pose inference
      matters most.
- [ ] **1.7** Stop a real recording from the panel and confirm with
      `ros2 bag info` that the bag is complete, readable, and contains exactly
      the topics the switches were set to. The SIGINT path is written to make
      this work; it needs proving once.
- [ ] **1.8** Decide the bind address. Localhost only, or the car network so a
      tablet can open it. See open question 9.

## Phase 2: the parts left as placeholders

- [ ] **2.1** Fill `instructions/*.md` with the real procedures. The wiring is
      done: one file per tab, read from the repo on every request. What is in
      them is placeholder text with a TODO line, waiting for the notes that
      already exist on the car computer.
- [ ] **2.2** Show free disk on the recordings volume in the recording tab. A
      recording that fills the disk halfway through a demo is the failure this
      would catch.
- [ ] **2.3** Show the name of the bag currently being written, and the last few
      that were, rather than just the directory.
- [ ] **2.4** Auto-refresh of the sensor sweep is off by default. Decide whether
      the status tab should re-check on a timer, and how often. A sweep costs
      `probe_seconds` of subscription per pass and nothing else.
- [ ] **2.5** A "check everything" button that runs the bag backend for 60
      seconds and shows the result next to the live numbers, for the times you
      want the trustworthy answer rather than the fast one.
- [ ] **2.6** **Build the panel's sensor list from a reference rosbag.** Today
      the sensors, their topics and their expected rates are hand-written in
      `config.json`, which is the part that has to be redone for every vehicle
      and the part most likely to drift from what the car actually publishes.

      Instead: record one bag with every sensor on and running at the rate it
      should, then hand the panel that bag's `metadata.yaml`. Dragging the
      metadata file alone is enough — the bag itself is not needed, and the
      drop zone for it already exists in the menu under "Configure new
      vehicle".

      What the panel derives from it:

      - **which sensors exist**, sorted into GNSS, cameras and lidar from the
        topic names and types
      - **the expected rate per sensor**, as `message_count / duration` from
        `topics_with_message_count`, **rounded to the nearest 0.5 Hz** — so a
        measured 19.87 becomes a target of 20.0, and 10.24 becomes 10.0. Half-Hz
        steps because sensor rates in practice land on 10, 20 and the occasional
        12.5, and rounding harder would erase a real difference.
      - **the topic list per sensor**, which is also what the recording
        switches are built from

      Those become the `expected_hz` each live reading is compared against, so
      the status lights are measured against a recording that was known good
      rather than against a number somebody typed.

      The catch to design around: the reference bag has to have been healthy.
      A bag recorded while the GNSS was still at 1 Hz would silently install
      1.0 Hz as the target and the panel would report green forever. The import
      should show what it derived and make somebody confirm it before it
      replaces the running config, rather than applying it straight away.

- [ ] **2.7** **Vehicle profiles.** One panel, several vehicles. Each is a saved
      config the panel can switch between, named and listed in the menu:

      | profile | what it is |
      |---|---|
      | `ava` | the car. Eight cameras, seven lidars, GNSS. The current defaults. |
      | `fusebike` | the bike. A different and much smaller sensor set. |
      | `robowilliam` | a roboracer template, starting from whatever it publishes. |

      A profile owns everything that makes the panel look the way it does for
      that vehicle: which sensor blocks exist and what they are called, the
      sensors in each, their expected rates, their topics, and which group
      buttons the recording tab shows. "All cameras" is not a useful button on a
      vehicle with one camera, so the blocks and their group switches have to
      come out of the profile rather than being hard-coded.

      Importing a bag's `metadata.yaml` (2.6) creates or updates a profile
      rather than editing one global config. Dropping a fusebike recording must
      not overwrite the car.

- [ ] **2.8** **Per-topic role, editable in the settings.** Today a sensor is
      `critical: true|false`, which is two states: it counts toward its block's
      health and records by default, or it does not. Widen that to three, listed
      per topic and changeable in the menu:

      | role | status tab | recording |
      |---|---|---|
      | **required** | counts toward the block; red here fails the block | on by default |
      | **not always required** | shown, can go red, never fails the block | off by default |
      | **ignore** | not shown at all | never offered |

      Two of the three already exist — `critical: true` and `critical: false`
      are exactly the first two rows — so the schema change is replacing the
      boolean with a three-valued `role`, and adding a filter that drops
      `ignore` before the status blocks and the recording switches are built.
      `critical` is read in six places (`sensors.py` twice, `recording.py` four
      times); all six become a comparison against the role.

      The editor lists every topic the profile knows about, which after 2.6 is
      every topic in the reference bag, with the three roles as a choice per
      row. That is what replaces hand-editing `config.json` to change which
      cameras are "required".

      For AVA the current presets are the defaults and should stay that way
      — every camera except the front-centre fisheye, every lidar except the two
      bumper units — but they stop being baked into the code.

      Open, and worth settling before building it:

      - Does editing a role write straight back to the profile on disk, or does
        it need a save step? Straight back is friendlier and is what a settings
        panel usually implies; a save step is safer on a car.
      - Is `ignore` per profile only, or does the panel also keep a global
        ignore list for topics no vehicle should ever show?

## Phase 3: not mine, but the tabs are there

Map, Prediction and Planning are placeholders on purpose. If somebody builds
them, adding a tab is one entry in `TABS` and one render function; the rails and
the layout do not change.

---

## Open questions

### Answered

- **GNSS failure mode.** It comes up at 1 Hz after a computer restart and stays
  there until somebody sets it. Once set it holds for the rest of the session.
  So the rate is genuinely wrong, not stale data published at the right rate,
  and measuring the rate is the correct instrument. No design change. It also
  means the check matters most in the first minutes after a restart, which is
  why the GNSS box sits at the top of the status tab.
- **The fourth perception signal.** It was mapping, and it is somebody else's
  standalone task, so it moved to its own tab. Perception stays at three:
  preprocessing, detection, pose inference.
- **Script location.** Everything the panel runs is in `~/scripts/`. Wired up.
- **Screen shape.** Portrait. The rails are now fixed at 160px and 76px so only
  the centre column shrinks, the status boxes are stacked rather than in a grid,
  recording sits over RViz at 70 / 30, and every font size is 50 percent larger
  than the first draft.
- **Recording topic selection.** Built: a switch per camera and per lidar, group
  switches per column, defaults set to the sensors that matter, and the result
  passed to the recording script as arguments and as `CODRIVER_TOPICS`.

### Blocking, and only answerable on the car

1. **Topic names.** What does each of the 16 sensors actually publish on? The
   defaults assume `/<sensor_name>/image_raw` and `/<sensor_name>/points`, which
   is a convention, not knowledge. `ros2 topic list` from the car settles it.
2. **GNSS topic and message type.** Which topic does it publish on? The failure
   mode is settled, the topic name is not.
3. **Recording script contract.** The panel now appends the selected topics to
   `~/scripts/start_recording.sh` as arguments, and sets `CODRIVER_TOPICS` to the
   same list. The script has to forward one of the two to `ros2 bag record`
   rather than carry its own topic list. What is it called today, and where does
   it write? The panel assumes `~/recordings/` and that a Ctrl-C ends it
   cleanly.
4. **Camera topic shape.** Each camera contributes `image_raw` and
   `camera_info`. If the cameras publish compressed images instead, or put
   `camera_info` somewhere other than the sibling namespace, the `record_topics`
   list per sensor is where that is fixed.
5. **Pipeline launch commands.** The exact command for preprocessing, detection
   and pose inference. A launch file, a script, a `ros2 run`?
6. **Do the operating-mode scripts need sudo?** If they prompt for a password
   they will hang silently when started from the panel. If so they need a
   passwordless sudoers entry or a wrapper.
7. **Python and rclpy.** Which Python version is on the car compute, and can it
   `import rclpy` after sourcing ROS? The panel targets 3.10 and needs the
   answer to be yes for the live probe. Everything else works either way.

### Needs a decision from you

8. **Should the lidar IMU go into the bag?** Ouster units publish `imu`
   alongside `points`, plus optional `scan`, `metadata` and the range, signal
   and reflectivity images. Only `points` is recorded today. Adding the IMU is
   one entry per lidar in `record_topics`, but it should be your decision rather
   than my default.
9. **Who should reach the panel?** It binds `127.0.0.1` today, so only the car
   compute can open it. Binding `0.0.0.0` puts it on the car network, where
   anything on that network can start a recording or stop a pipeline. There is
   no authentication and there should not be one for something this small, so
   this is a decision about the network, not about the code.
10. **Should closing the panel stop the demo?** Right now stopping the panel
    stops every child it started, so a closed panel never leaves an invisible
    recorder holding a bag open. The other reading is that the demo should
    survive a panel restart. Currently it does not.
11. **Two browsers.** Nothing stops two tabs from both pressing start. The
    backend refuses the second start of an already-running process, so the worst
    case is a confusing moment rather than two recorders. Worth flagging in case
    somebody wants it locked down.
12. **Fisheye rate.** The front-centre fisheye is listed at 20 Hz like the
    others. If it actually runs at a different rate, one config line fixes it,
    but it will show red until then.

### Worth confirming, not urgent

13. **Tolerance.** A rate counts as good within 15 percent of nominal, so 20 Hz
    passes between 17 and 23. Tight enough to catch a GNSS at 1 Hz by a wide
    margin. If cameras normally sit at 19.2 Hz that is still fine; if they
    normally sit at 16 Hz the tolerance is wrong and the expectation is wrong.
14. **Probe window.** Two seconds per sweep. Long enough to tell 10 Hz from
    1 Hz, short enough that the status tab does not feel stuck. If the numbers
    look noisy on the car, raising it is one config key.
15. **Which notes to copy off the car.** `instructions/*.md` are placeholders
    with a TODO line each. Whatever is already written on the car computer can
    replace them wholesale, one file per tab.

---

## How to work on it from here

The whole panel runs on a laptop with no ROS:

```bash
CODRIVER_CONFIG=examples/demo.json uv run python -m codriver --open
```

Every remaining answer is a config edit rather than a code change. The two that
would have needed real work, the GNSS failure mode and the fourth perception
signal, are both settled.
