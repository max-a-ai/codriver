# Agent Coding Standards

Enforce on every change.

## Hard rules

- **UV only.** `uv run`, `uv sync`, `uv add`. Never `pip` directly.
  Reproducibility is paramount.
- **Python version** is pinned in `.python-version` and `pyproject.toml` (3.10, set by ROS 2 Humble). Do not silently upgrade.
  Don't silently upgrade.
- **Line length: 79.** Ruff enforces. No escape hatches.
- **Functions ≤ ~70 lines.** Split if longer.
- **Type hints everywhere.** `mypy --strict` must pass.
- **Format with Ruff:** `uv run ruff format` + `uv run ruff check --fix`.
- **Slim-first.** Prefer stdlib + subprocess over heavy frameworks. New
  runtime deps need a rationale line in `HANDOFF.md`'s decisions table.

## Layout (fixed)

- Flat package `codriver/` at the repo root, named after the repo.
- This project has **no ML subpackages** (`data/ models/ losses/ metrics/
  train/`) and no `slurm/`: it is a zero-dependency web panel, not a
  training repo. `HANDOFF.md` lists every deviation and why.
- Entry point is the console script `codriver = codriver.__main__:main`.
  Demo config and stand-in scripts in `configs/`, quick checks in
  `notebooks/`, `resources/` and `outputs/` gitignored and empty for now.
  Full tree: `HANDOFF.md`.
- **Zero runtime dependencies is a hard constraint**, not a preference:
  the panel runs in the ROS-sourced system interpreter. A new runtime
  dep needs a very good reason and a row in `HANDOFF.md`.

## Workflow

- Keep `.docs/progress.md` updated each session. It has three parts
  sharing the same section names: the gantt timetable at the top, the
  `# Log` in the middle, `# Todos` at the bottom.
- Append log entries as `### YYYY-MM-DD HH:MM — <what> (<commit>)` under
  the section the work belongs to, so any line traces back to a diff.
- Promote finished todos by deleting them; add newly-discovered ones
  under the matching section.
- Keep `HANDOFF.md` current. When you learn something future-you would
  need to pick this up cold, write it down there.
- There are no training runs here, so `outputs/` and `.docs/runs/` stay
  empty until the local model arrives.
- The frontend has no test runner. Changes to
  `codriver/static/index.html` are verified by driving headless Chrome
  against the demo config and looking at the result.

## Verification before saying "done"

1. `uv run ruff check .` → zero errors
2. `uv run ruff format --check .` → clean
3. `uv run mypy` → zero errors
4. `uv run pytest` → green
5. If there's an entry point: `uv run <script-name>` → it launches
   without crashing on the expected platform.

## Directories

`resources/` and `outputs/` are gitignored and built per machine by
`python3 <module>/scripts/dm_link.py`. Never commit them, never
hand-create another name for the same idea, and never put a `.venv`
inside an HPC workspace — those filesystems are limited by inodes.
