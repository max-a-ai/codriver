# codriver — Handoff

Generated: 2026-09-14

---

## Status Snapshot

The panel is built and runs. Everything in it was built against invented
sensors and stand-in scripts, so the shape is settled but **none of it has
touched the car yet** — every topic name and expected rate in the config is
still a guess.

All quality gates pass:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy` (strict)
- `uv run pytest` — 59 tests

See it without a car or ROS:

```bash
CODRIVER_CONFIG=configs/demo.json uv run codriver --open
```

Next up: the vehicle-profile block (P1–P3 in `.docs/progress.md`), then the
related-work positioning for the HCII paper.

---

## Goal

A control panel for a ROS 2 research vehicle, opened in a browser on the car
compute. It answers "are the sensors healthy" at a glance and starts and stops
the demo without a terminal. It is growing a natural-language layer: a local
model, retrieval over *this vehicle's own repository*, and speech — so the
thing you would otherwise type into three terminals can be asked out loud.

---

## Confirmed Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Python version | **3.10** (`>=3.10,<3.14`) | **Override of the 3.13 default.** Ubuntu 22.04 + ROS 2 Humble ships 3.10 and the panel must run in the interpreter that can `import rclpy`. |
| Runtime dependencies | **none** | The panel runs in the ROS-sourced *system* Python. A dependency would mean a venv with `--system-site-packages` or a `pip install --user` on a car. Zero deps means `source setup.bash && python3 -m codriver`. |
| Package manager | **UV** | `uv sync`, `uv run`. |
| Build backend | **hatchling** | Was `uv_build`; moved to the standard. |
| Project layout | **flat**: `codriver/` | one folder named after the repo. Was `src/codriver/`. |
| Linter / formatter | **Ruff** (79 cols) | Was 100; reflowed 2026-09-14. |
| Type checker | **mypy** (strict) on `codriver/ tests/` | `rclpy.*` is `ignore_missing_imports`: it only exists in a ROS-sourced environment and is imported lazily. |
| Console script | `codriver = "codriver.__main__:main"` | Not `app:main` — `app.py` holds the application state, and the CLI has always been `__main__`. |
| Frontend | **one static HTML file**, no framework, no build step, no CDN | Same reason as zero deps. `codriver/static/index.html` is the whole client; it polls a JSON API on the same origin. |
| Visualiser to embed | **Foxglove**, not RViz | Only Foxglove can render inside a browser page (`foxglove_bridge` is a WebSocket, Studio self-hosts in an iframe). RViz is Qt and would need noVNC/WebRTC screen streaming. |

---

## Deviations from the python-project-init contract

The standard tree is shaped for an ML project. Codriver is a zero-dependency
web panel: no datasets, no checkpoints, no training runs. What was skipped and
why:

| Standard item | Here | Why |
|---|---|---|
| `codriver/{data,models,losses,metrics,train}/` | **not created** | No datasets, architectures, losses, metrics or trainer. Creating five empty packages would be cargo cult. Revisit if the RAG work grows an indexer worth its own subpackage. |
| `codriver/scripts/<repo>-main.py`, `-eval.py` | **not created** | Nothing to train or evaluate. The entry point is the console script. |
| `codriver/slurm/` | **not created** | No cluster. |
| `codriver/scripts/dm_link.py` | **not created** | The `dm_*` scripts were not on disk in the data-management skill, and there is nothing per-machine to link yet. |
| `resources/`, `outputs/` | gitignored, **empty** | Kept so the layout matches and so the model weights (L3) and RAG index have somewhere to live. |
| `config-global.json` | **minimal stub** | Nothing reads it yet. It becomes real when the local model and the retrieval index need per-machine paths. |
| `notebooks/capabilities.ipynb` | **not written** | The demo config is the capabilities check: `CODRIVER_CONFIG=configs/demo.json uv run codriver`. |

Project-specific additions, all at allowed locations:

- `codriver/instructions/` — one `<tab-id>.md` per tab, opened by the panel's
  right-hand rail. Inside the package so it ships with the wheel.
- `codriver/static/index.html` — the entire frontend.
- `codriver/ros/` — the four rate backends behind one interface.
- `configs/demo.json` + `configs/demo-scripts/` — the off-car demo.

---

## Repository Structure

```
car-ui/                      # repo dir is still car-ui; the project is codriver
├── codriver/                # THE package, flat
│   ├── instructions/        #   one <tab-id>.md per tab, shipped with the wheel
│   ├── ros/                 #   rate backends: live (rclpy), bag, cli, mock
│   ├── static/index.html    #   the whole frontend, one file
│   ├── app.py               #   application state and the JSON the browser gets
│   ├── config.py            #   sensors, processes, commands; the JSON loader
│   ├── processes.py         #   start, watch and Ctrl-C the children
│   ├── recording.py         #   which sensors go into the next bag
│   ├── sensors.py           #   readings to lights
│   ├── server.py            #   HTTP: static file + small JSON API
│   └── __init__.py  __main__.py  py.typed
├── configs/                 # demo.json + demo-scripts/ (stand-ins for the car)
├── notebooks/  tests/  third_party/
├── .docs/                   # the record (hidden: needs `tree -a`)
│   ├── progress.md          #   timetable + log + todos, same section names
│   ├── related-work.md      #   the four systems we differentiate against
│   ├── figures/             #   the README screenshots
│   └── latex-draft/  runs/
├── resources/  outputs/     # gitignored, empty for now
├── config-global.json  pyproject.toml  uv.lock  .python-version
├── README.md  HANDOFF.md  instructions.md
└── .gitignore
```

### .docs/

`.docs/progress.md` is the single source of truth for what is done and what is
next: a gantt timetable at the top, a dated `# Log` in the middle, `# Todos` at
the bottom, all three sharing the same five section names — **Panel**, **On the
car**, **Language & retrieval**, **Speech**, **Paper**.

`.docs/` is dot-prefixed and hidden by default in Obsidian and most file
browsers; enable "Show hidden files" to see it.

---

## Things that will bite you

- **`git push` is the user's to run.** Print the command; never run it.
- **The frontend has no build step and no test runner.** Changes to
  `index.html` are verified by driving a headless Chrome against the demo
  config and looking at the screenshot. `uv run pytest` does not cover it.
- **`ready_pattern` per pipeline is guesswork** until C6 is done on the car;
  pose inference stays orange for most of a minute by design.
- **The exclusive group** ties the recorder and the visualiser together. They
  live on different tabs now, so both tabs have to explain why the other is
  unavailable.
- **`globalopenhack/` and `graphify-out/` are gitignored** working material,
  not part of the project.

---

## For the Next Handoff

1. Read this file top-to-bottom.
2. Read `.docs/progress.md` — timetable, log, open todos.
3. Read `instructions.md` for the coding standards (ruff + mypy enforce them).
4. `uv sync` to reproduce the environment.
5. `CODRIVER_CONFIG=configs/demo.json uv run codriver --open` to see it.
6. When you finish a session, append a dated entry under the right `# Log`
   section of `.docs/progress.md`, prune its `# Todos`, and update this file
   if you learned something future-you would need to pick up cold.
