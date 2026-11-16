# Agent runtime: unified base image + gitFS-backed agent config

## Problem

The current image stack has a split that no longer matches the intended design:

- `base` had Herdr/Ovis; `devpod` inherited them; `headless` inherited them too —
  making "headless" not headless.
- `devpod` had its own kubectl download (pinned, sha256-verified) that duplicated
  what base should already have.
- Agent config (skills, extensions, APPEND_SYSTEM.md) was baked into the image
  via the npm catalog, so it could not be updated without rebuilding the image.
- `~/.pi/agent` was not a volume; it was ephemeral image state.

## Target design

### 1. One unified `base-agent-runtime` image

Everything the agents need lives in `base/Dockerfile`:

| Component | Source |
| --- | --- |
| Node 22.23.4 + npm | `node:22.23.4-bookworm-slim` |
| Bun 1.4.4 | `oven/bun:1.4.4` (binary copy) |
| Pi + 4 extensions | npm `ci` from committed lockfile |
| Herdr 0.9.5 | GitHub release binary + SHA-256 |
| Ovis 0.5.1 | `devswha/ovis` pinned commit, built from source |
| kubectl v1.36.6 | dl.k8s.io release + sha256 |
| gh, git, jq, curl, tini, unzip | apt |
| ast-grep | pi-lens postinstall |

**Per-image deltas are only `ENTRYPOINT`/`CMD`/`AGENT_PROFILE`:**

| Image | Inherits | Adds | CMD |
| --- | --- | --- | --- |
| `base` | — | — | `pi` |
| `devpod` | base | apt: bash-completion, fd-find, less, nano, openssh-client, ripgrep, tmux | `bash` |
| `headless` | base | — | `pi --mode rpc --no-session --no-approve --no-extensions --no-skills --no-prompt-templates --no-context-files` |
| `_template` | base | — | `pi` |

Herdr/Ovis are present in all images for debugging; they are **not** the
entrypoint in any of them. `tini` stays as the PID-1 supervisor.

### 2. `~/.pi/agent` is a PVC, populated by a gitFS

`~/.pi/` is a **local-path PVC** that auto-cleans when the pod is deleted.
An `initContainer` clones `github.com/rodoyle/my-agent.git#<branch>` directly
into `~/.pi/agent`. This supplies:

- `~/.pi/agent/skills/` — task-execution, verification, kubernetes-dev
- `~/.pi/agent/extensions/` — task-contract.ts
- `~/.pi/agent/APPEND_SYSTEM.md` — the autonomous execution contract
- `~/.pi/agent/settings.json`, `models.json` — agent-level settings

The image still bakes `/opt/pi-defaults/<profile>/settings.json` (seeded at
startup by `agent-entrypoint.sh` via `profile-config.mjs initialize`), but
the gitFS overrides it for skills/extensions/system prompt. A ConfigMap can
override `models.json` (and `mcp.json`) read-only on top.

### 3. Task contract is a controller mount, not baked

`.agent/task.json`, `.agent/environment.yaml`, `.agent/result.json` are
mounted into the pod by the controller. The image does not contain them.

## Changes made

| File | Change |
| --- | --- |
| `base/Dockerfile` | Added pinned kubectl download (after Herdr, before ovis-build). kubectl now in base. |
| `devpod/Dockerfile` | Removed kubectl block (inherited from base). Removed `kubectl version` smoke check. Kept apt tooling. |
| `headless_agent/run.sh` | Skills/extensions/APPEND_SYSTEM.md now loaded from `$PI_CODING_AGENT_DIR` (gitFS), not `/workspace/.pi/`. |
| `headless_agent/headless-agent-pod.yaml` | Rewired: initContainer clones my-agent.git into `~/.pi/agent`; PVC for `~/.pi/agent`; task contract mounted at `/workspace/.agent`. |

## Verification

```sh
cd agents
node --check tests/image-smoke.mjs
node --check base/profile-config.mjs
node --test tests/profile-config.test.mjs
python3 -m unittest discover -s tests -v
sh -n base/agent-entrypoint.sh base/ovis.sh
sh -n headless_agent/run.sh
```

All pass.

## Open items

- `my-agent.git` repo layout for skills/extensions needs to be finalized
  (currently `headless_agent/.pi/` has the content; it should move into the
  my-agent submodule).
- The initContainer uses `busybox` + `git`. The base image already has git;
  an alternative is to use the base image itself as the initContainer.
- `~/.pi/agent` PVC: confirm local-path provisioner and auto-cleanup policy.
- `task` PVC (for `.agent/task.json` etc.): confirm whether it should be a
  PVC or a ConfigMap.