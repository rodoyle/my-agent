# Agent image verification — 2026-11-09

## Prompt-to-artifact checklist

| Requested result | Artifact and observed evidence | Status |
| --- | --- | --- |
| Flesh out base image | `base/Dockerfile`: actual Node/Bun/Pi/extensions/Herdr/Ovis/Kubernetes client/git/gh installation; native Kaniko build and deployed smoke passed | Satisfied |
| Flesh out interactive devpod | `devpod/Dockerfile`: exact base digest used, kubectl 1.36.6 and interactive tools installed; native Kaniko build and deployed smoke passed | Satisfied |
| Consistent Node/npm versus Bun policy | Node 22.23.4/npm 10.9.9 host Pi 1.5.0 and extensions; Bun 1.4.4 builds/runs Ovis; no node-to-Bun substitution | Satisfied |
| Research the runtime choice | `agent-images.md` links upstream Node requirement, package installation and SDK/Bun distinction | Satisfied |
| Details under `docs/plans/` | `agent-images.md`, this report and `evidence/agent-images-2026-11-09.json` | Satisfied |
| Build using Kaniko in k3s `build` | Four successful Kaniko Jobs on `med-laptop-2`, linux/amd64, with isolated context ConfigMaps | Satisfied |
| Supporting agents inherit the policy | Headless and template images built from the exact base digest; headless default RPC command ran and exited 0 without credentials | Satisfied |

## Published build artifacts

Registry used for this verification: the existing internal build registry at
`192.168.0.48:30500`; tag `goal-20261109`. These are **not** GHCR publications.
The final source files in the explicit build-context allowlist were compared
byte-for-byte to the successful base Job's submitted ConfigMap and were
identical. The generator's separate Job identity logic was subsequently fixed
to include node and registry-transport options; that does not alter image bytes.

| Image | Successful Job | Digest |
| --- | --- | --- |
| `agents-base` | `agents-base-db7f9c1178` | `sha256:ece13bedf90ecb81e06ea32511bec79764579b6ace15161413218043425d7c39` |
| `agents-devpod` | `agents-devpod-a200007397` | `sha256:780a0d8780a161eeab7a72fad75c7561dc3985e69543167e5a48f29c87901744` |
| `agents-headless` | `agents-headless-ba2b01156e` | `sha256:55d66a116099d447e59feb58d37e7ca4d733a255154b24fd22e8b424c24a734c` |
| `agents-template` | `agents-template-ae6554281a` | `sha256:b5bcc2483d4e9bdb539ee432677e302cc942bf038457369377701b1edec07304` |

The raw non-secret pod-status/termination records and selected gate output are
saved in `evidence/agent-images-2026-11-09.json`. All four successful Kaniko
containers exited 0 and wrote their pushed digest to the termination message.
The record also preserves the initial failed base build, not just successes.
Temporary Jobs, ConfigMaps and smoke Pods were deleted after evidence capture;
images remain in the registry.

## Behavioral observations

Base and devpod's build-time gates, then separate deployed Kubernetes smoke
Pods, each reported:

```text
v22.23.4
10.9.9
1.4.4
1.5.0
herdr 0.9.5
git version 2.39.5
gh version 2.23.0 (2023-02-27 Debian 2.23.0+dfsg1-1)
ast-grep 0.51.0
PASS: non-root Node Pi RPC and all four extension registrations; native AST and Kubernetes imports
```

The base smoke pod and devpod smoke pod used UID/GID 1000, empty HOME/workspace
volumes, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, all
Linux capabilities dropped, RuntimeDefault seccomp, and no service-account
mount. Both terminated successfully. They exercised the real image entrypoint,
seed relocation into an empty HOME, a native AST parse, Kubernetes module
import, and real Pi `get_state`/`get_commands` responses with all four extension
source paths. No LLM prompt/provider request or credentials were used.

The headless smoke pod retained the image's default CMD, rather than replacing
it with the interactive smoke command. With closed stdin, its default Pi RPC
process exited 0. This verifies boot/shutdown, not model inference or the
unfinished issue controller. Ovis's frontend and matching Rust PTY host built
successfully; no authenticated browser/Herdr session was started.

## Failed checks and correction evidence

| Failure class/signature | Falsifiable cause and correction | Recheck |
| --- | --- | --- |
| IMPLEMENTATION_DEFECT: initial base smoke assertion `No loaded commands from pi-subagents` | `pi install` rewrites local sources relative to its settings directory. Moving that directory made all seed package paths invalid. Normalize those paths to absolute paths before baking the seed; retain the loaded-command assertion. Local isolated `pi install` reproduced relative-path storage. | Corrected base build passed the same check; deployed base/devpod smoke passed it again with empty mounted HOME. |
| ENVIRONMENT_CAPABILITY: runtime pull of `192.168.0.48:30500/...` returned HTTP response to HTTPS client | The registry is HTTP-only, while containerd treats non-loopback registries as HTTPS. Use the existing NodePort via `localhost:30500`, where containerd supports loopback HTTP by default. No node registry config, TLS verification policy, cluster RBAC or image test was weakened. | All three image smoke Pods pulled the exact built digests via loopback and exited 0. |
| DETERMINISTIC_CONFIG: user-run kubeconfig helper's GNU `base64 -w0` fails on macOS | Use stdin encoding plus newline stripping; use BSD `date` fallback for expiry parsing. Agent did not execute key generation or read key/certificate material. | Shell syntax, inert base64 round-trip, BSD expiry parsing passed; user subsequently minted the identity and granted the narrow build Role. |
| IMPLEMENTATION_DEFECT identified in review: generated Job name unchanged when node/registry transport changed | Include both effective options in the build fingerprint. | New regression checks independently change each option and require a fresh Job name. |

## Local gates and independent review

From the infra root:

- `timeout 60 python3 -m unittest discover -s agents/tests -v`: **7 passed**.
  Fixtures include harmless README changes versus actual runtime-source changes,
  real-file staging from projected symlinks, empty HOME seeding, preservation of
  custom settings, exit status propagation, and remote Ovis binding rejection.
- `node --check agents/tests/image-smoke.mjs`: passed.
- `sh -n agents/base/agent-entrypoint.sh agents/base/ovis.sh`: passed.
- `bash -n scripts/make-agent-kubeconfig.sh`: passed.
- Active LSP probes of the changed Python, JavaScript, Dockerfiles, shell and
  YAML sources: 12 files checked, zero diagnostics/errors.
- `git -C agents diff --check` and parent `git diff --check`: passed.

A fresh-context read-only reviewer checked runtime separation, Pi trust flags,
entrypoint behavior and Kaniko isolation against installed Pi 1.5.0 source.
It independently confirmed the relative-path root cause and identified the
Job-fingerprint defect fixed above. Its role had no execution tool; local test
results were supplied by the parent, not falsely represented as rerun by the
reviewer. Cluster builds and deployed smoke were executed by the parent.

## Boundaries and follow-ups

- Only linux/amd64 was built and executed here; arm64 upstream artifacts exist
  but a native arm64 release is not claimed.
- No live LLM call, provider credential, browser login/pairing, or issue-to-PR
  controller workflow was exercised. Those are not fabricated readiness claims.
- The registry is internal/HTTP and not a production publication path. The
  separately queued update/rebuild/GHCR automation item owns that pipeline.
- Separately queued work owns extension/configuration profiles per agent.
  A proposed source-build stage for Herdr is still in drafting, not adopted;
  these images currently use verified upstream binaries and contain no Rust
  toolchain.
- The user revoked the temporary build RoleBinding. Final agent-identity checks
  found no `pi-agent-image-build-task` binding and returned `no` for creating
  Jobs in `build`; `environment.yaml` is restored to base identity only.
- The agents submodule implementation is published on its `main` branch. The
  parent infra branch had pre-existing divergent history; the user explicitly
  chose to retain its commits locally rather than force-push or reconcile that
  unrelated history as part of this image goal.
