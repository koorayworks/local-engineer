# Local Engineer v0.1

Mac mini local-agent layer for Bonsai 2 27B, Technocore integration, and registered development/keyboard-firmware projects in WSL.

> **Maturity: experimental / active development.** The runtime has durable checkpoints, bounded editing, project-specific build/test commands, and verification tools, but agent runs can still stall or stop before a build. Resume and inspect the saved evidence rather than assuming a task completed. Application guardrails are not an OS sandbox.

## Install

From the repository root:

```bash
git clone --branch local-engineer-v0.1 --single-branch https://github.com/vwbugowner1976/local-engineer.git ~/local-engineer-src
cd ~/local-engineer-src/local-engineer
./install.sh
source ~/.zshrc
```

## LLM switching

```bash
llm status
llm bonsai
llm bonsai-tech
llm qwen
llm stop
llm logs
```

- `llm bonsai`: stop Technocore/Qwen and give Bonsai the machine for Local Engineer.
- `llm bonsai-tech`: Bonsai + Technocore using `TECHNOCORE_LLM_BACKEND=managed_bonsai`. Run this only after the Technocore backend patch succeeds.
- `llm qwen`: stop Bonsai and restore `managed_mlx`.

Bonsai runs from the existing `~/Bonsai-demo` installation with PQ2_0, Metal, context 8192, text-only mode, and a server-wide reasoning budget of 2048.

## WSL projects

Default SSH alias: `wsl`.

```bash
local-engineer status
local-engineer projects
local-engineer doctor
local-engineer discover
local-engineer build prospector
local-engineer build rmk-pg1kb
local-engineer inspect prospector "Check the registered project facts and relevant source before proposing a change"
```

Override the SSH host with `LOCAL_ENGINEER_SSH_HOST` or edit `~/.config/local-engineer/projects.json`.

## Autonomous repair

```bash
local-engineer fix prospector "Build locally, diagnose the current error, make the smallest safe fix, and rebuild."

local-engineer fix rmk-pg1kb "Investigate the trackball regression, preserve working behavior, fix it, and build."
```

The agent can inspect/search files, make bounded file edits, run configured builds/tests, and inspect diffs. It does not push or commit. Destructive/admin/network commands are blocked where recognized. Files touched by a run are backed up under `~/.local/state/local-engineer/backups/`.

**Safety note:** builds and tests execute project code under the configured user's permissions. This is a guardrail layer, not a security sandbox. Review project registry commands and use isolated checkouts for unfamiliar code.

## Add Bonsai backend to the current local Technocore

```bash
llm bonsai
local-engineer technocore-bonsai
```

This asks Bonsai to inspect the current Mac-side Technocore tree (not the older GitHub snapshot) and add `managed_bonsai` beside `managed_mlx`, preserving existing behavior and tests.

When the patch and tests succeed:

```bash
llm bonsai-tech
```

The manager checks that no `mlx_worker.py` appears in Bonsai mode; if one does, it stops Technocore again to avoid another 16 GB unified-memory collision.

## Durable sessions and resume

The existing project/tool layer uses `engineer_runtime.py` for durable sessions. No service is stopped automatically when the API is unavailable. The running model must identify as Bonsai. Context is measured with the server template/tokenizer, reserving output space in the 8192-token context. Search remains available during repair.

```sh
local-engineer ask "prospector: investigate the peer display regression"
local-engineer resume ~/.local/state/local-engineer/sessions/RUN/working_state.json
python3 -m unittest -v test_runtime
python3 benchmark.py --level 4
```

Sessions save structured state, tool evidence, token/time metrics and backups after each tool. Resume rechecks Git and invalidates reads and verification from before the interruption. Project memory is a hint; current repository instructions win. Only one run per project is permitted on each orchestration host.

Registry fields: `root`, `transport` (`local` or `ssh`), `ssh_host`, `preferred_branch`, `protected_branches`, `build`, `clean_build`, `test`, `artifact_path`, `notes`, `context_length`. Defaults protect main/master. SSH projects additionally require `runtime_dir` on the destination containing `engineer_runtime.py`, so command timeout enforcement runs on the execution host.

SSH authentication and host resolution must already work; this program does not modify credentials or SSH configuration. WSL can also run the same Python CLI with `BONSAI_API_BASE` pointing at an authenticated SSH local forward.

For ZMK projects, the agent can inspect `config/west.yml` or `west.yml` and reports v0.3/v0.4 only when the ZMK project's revision explicitly identifies that release family. Branch names and commit hashes without release evidence are reported as `ZMK_VERSION_UNKNOWN`; the agent must not select a version-specific environment from an unknown result.

Commands are exact trusted registry commands or limited read-only Git / Python test invocations. Builds/tests execute project code: this is a guardrail, not an OS sandbox. Review registry commands and use isolated checkouts for unfamiliar code. Existing user files cannot be fully overwritten initially; exact replacements retain the rest and back up their original content. Branches are never switched, and commits/pushes are never performed automatically.

Live benchmark levels 1–5 create disposable repos without commits. They test build discovery, status reporting, compiler-error localization, single-file repair, and multi-file repair. Level 6 uses an actual project with external acceptance tests; hardware regression checks must be reported separately from offline compilation.

## Known limitations

- SSH/WSL availability depends on the tunnel and remote runtime being reachable; a failed connection is not a build failure.
- The agent may repeat discovery or stall before invoking a build/test tool. Check the session's `working_state.json` and `events.jsonl` to determine what actually ran.
- Shell commands rejected by the guard must be retried as separate, permitted operations; a rejected command is not evidence that the underlying project command failed.
- Synthetic benchmark success does not establish reliability on every real project, and successful firmware compilation does not prove hardware behavior.
- Verify the final `git diff`, build/test tool outputs, and artifact copy results before calling work complete.

## Live status viewer

See [LIVE.md](LIVE.md) for the local status/event viewer, macOS LaunchAgent setup, and the sanitized `live-status` branch integration.


## Control Center prototype

The first Control Center implementation is intentionally separate from the existing read-only live viewer. It adds a responsive Japanese web UI, direct planning-only chat with the local Bonsai OpenAI-compatible API, and a persistent instruction queue. Chat now shows an immediate “考えています…” placeholder and streams visible answer text as it arrives. Empty-content responses are reported as errors; internal `reasoning_content` is deliberately not displayed.

Run from this directory:

```bash
python3 control_center.py --host 127.0.0.1 --port 8766
```

Open `http://127.0.0.1:8766/` and enter the bearer token printed at startup. The token is stored at `~/.local/state/local-engineer/control-center/auth.token` with owner-only permissions where supported. API requests require the token. The queue is persisted at `~/.local/state/local-engineer/control-center/tasks.json`.

For phone access on a trusted LAN, bind explicitly to the Mac's reachable interface or `0.0.0.0` and use the token. Do not expose this server through an unauthenticated public endpoint or Funnel. Prefer access through a trusted private network such as Tailscale and keep the token private.

The queue panel can ask Bonsai to propose a bounded JSON plan (up to eight steps). The user reviews the summary and steps and explicitly approves adding them to the persistent queue. Batch registration validates the steps and saves them together. This is **planning and queue registration only**: queued items are still not executed by Local Engineer. Status and event data are read from the existing session files. No task is marked complete based on chat output. Automatic queue dispatch, stop/resume/cancel integration, external AI adapters, and full end-to-end verification remain future steps.

Run the new unit tests alongside the existing runtime tests:

```bash
python3 -m unittest -v test_control_center
python3 -m unittest -v test_runtime
```
