# Local Engineer

**Local-first coding agent for Japanese natural-language software and firmware maintenance.**

Local Engineer connects a locally hosted Bonsai model to registered development projects. It is designed to inspect a real checkout, form an evidence-based hypothesis, make bounded changes, run the project's configured build/tests, verify the diff, and report what actually happened.

> **Project status: Experimental / active development.** This README describes intended capabilities and implemented guardrails, not a claim of production readiness. A task can still stall in tool selection or discovery, and a saved session does not guarantee that work completed. Treat build/test status and the recorded tool results as evidence; never infer success from a final summary alone.

## What it is designed to do

```text
PLAN → INSPECT → HYPOTHESIS → EDIT → BUILD/TEST → VERIFY → GIT DIFF → REPORT
```

- Use a local Bonsai model through an OpenAI-compatible API.
- Operate on registered local or SSH-accessible projects (including WSL).
- Inspect repository state and project instructions before editing.
- Make bounded file edits, backing up files before changes.
- Run only the build/test commands configured for the project.
- Save durable session state, tool evidence, timing/token metrics, and checkpoints; resume by rechecking Git state and invalidating stale evidence.
- For configured ZMK projects, discover build targets and verify/copy generated UF2 artifacts without silently overwriting existing destination files.
- Publish a sanitized operational snapshot to the separate `live-status` branch for read-only monitoring.

The model proposes and selects actions; the runtime enforces tool and path boundaries. These controls reduce risk but do not make arbitrary project code safe.

## Current scope

Local Engineer is a project runner, not a general-purpose hosted coding service. It depends on:

- A working local Bonsai API (default: `http://127.0.0.1:8080/v1`).
- A project registry at `~/.config/local-engineer/projects.json`.
- Existing Git checkouts and, for SSH projects, working SSH authentication and a reachable remote runtime.
- Correct, reviewed build/test commands in the project registry.

Example registered projects in the current setup include keyboard/firmware work such as KoZakura, Prospector, and RMK. Your registry determines which projects are actually available on a given machine.

## Quick start (macOS)

The implementation and its installation scripts live in `local-engineer/`:

```bash
git clone --branch local-engineer-v0.1 --single-branch https://github.com/koorayworks/local-engineer.git ~/local-engineer-src
cd ~/local-engineer-src/local-engineer
./install.sh
source ~/.zshrc
```

Confirm the model, registry, and connections before running a task:

```bash
local-engineer status
local-engineer projects
local-engineer doctor
```

Typical commands:

```bash
local-engineer inspect prospector "Inspect the current state and relevant source"
local-engineer build prospector
local-engineer fix prospector "Find the cause, make the smallest safe fix, and verify it"
local-engineer ask "kozakura: inspect the current build configuration"
local-engineer resume ~/.local/state/local-engineer/sessions/<session-id>/working_state.json
```

The exact commands and project names depend on the installed version and local registry. Review `local-engineer/README.md` for model switching, WSL setup, and live-status details.

## Safety boundaries

- Main/master and other configured protected branches are protected from agent edits.
- File paths are checked; sensitive-looking paths and path escapes are rejected.
- Existing files are not meant to be replaced wholesale when an exact edit can preserve user content; original contents are backed up.
- Destructive, administrative, network, push, and commit operations are blocked by the command guard where recognized.
- Local Engineer does not automatically commit or push changes.
- SSH credentials and host configuration must already be set up; Local Engineer does not create or repair them automatically.

**Important limitation:** these are application-level guardrails, not an operating-system sandbox. Builds and tests execute project code with the permissions of the configured user. Use isolated checkouts for unfamiliar projects and review registry commands before enabling automated builds.

## Verification and benchmarking

From the implementation directory:

```bash
python3 -m unittest -v test_runtime
python3 benchmark.py --level 4
```

The disposable benchmark levels 1–5 exercise progressively more complex build discovery, status reporting, error localization, and repair tasks. Results from synthetic benchmarks are not proof of reliable performance on every real repository or hardware target. Hardware behavior must be verified separately from successful compilation.

Do not describe a task as complete unless the relevant build/test tool result and final diff checks support that conclusion.

## Repository layout

- `local-engineer/` — Local Engineer CLI, durable runtime, tests, installation and live-status tools.
- Top-level Technocore Tech Radar files — a separate, retained project area; they are not required to run Local Engineer.

The public `live-status` branch contains a sanitized status snapshot only. It is a monitoring surface, not a remote control channel.

## English summary

Local Engineer is an experimental, local-first coding agent for registered projects, powered by a locally served Bonsai model. It supports bounded edits, configured builds/tests, Git verification, resumable checkpoints, SSH/WSL execution, and ZMK UF2 artifact handling. It has useful guardrails, but is not a production-grade autonomous engineer or a security sandbox. Always inspect the evidence, diffs, and actual verification results.
