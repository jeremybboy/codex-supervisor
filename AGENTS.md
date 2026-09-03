# AGENTS.md

## Purpose

Codex Supervisor is a local, read-only observer for coding-agent activity.

## Canonical files

- `supervisor.py`: server, Codex adapter, filtering, and state derivation.
- `index.html`: dependency-free local dashboard.
- `tests/`: parser and safety regression tests.
- `docs/architecture.md`: boundaries and adapter contract.

## Invariants

- Never edit, message, approve, or otherwise control a watched worker task.
- Never expose encrypted or hidden reasoning.
- Keep captured events memory-only by default.
- Explicit user-decision evidence outranks optional model interpretation.
- Treat rollout JSONL as unstable and fail visibly on incompatible records.

## Checks

Run `python3 -m unittest discover -s tests` and `python3 -m py_compile supervisor.py`.

## GitHub workflow

After bootstrap, never change the default branch directly. Use a feature branch, stage explicit paths, open a PR, and never merge it for the user.
