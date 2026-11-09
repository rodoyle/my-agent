# Headless Pi worker

The container is a **Node-hosted Pi RPC worker** based on `base/Dockerfile`.
Build it with Kaniko in the `build` namespace; see
[the image plan](../docs/plans/agent-images.md). It does not run the SDK example.

Pi's CLI runs under Node (>=22.19), installed by npm from the base's committed
lockfile. Bun remains available for project tooling and Ovis. Pi's upstream SDK
also permits Bun hosts, but that is not the runtime selected for these images.
Do not substitute `bun --bun pi`, alias `node` to Bun, or install a second Pi.

## RPC mode

The image accepts newline-delimited Pi RPC commands on stdin and returns
protocol events on stdout. For example, send
`{"id":"state","type":"get_state"}` and close stdin to shut down cleanly.
Use a controller with deadlines and proper stream handling, not a long-running
shell pipeline. No provider call is needed to query state.

Default arguments disable automatic extension/skill/prompt/context discovery
and do not trust project configuration. The controller can replace the command
with `pi --mode rpc --no-session --no-approve --no-extensions -e <reviewed-path>`
and explicit reviewed skills/prompts. Do not enable executable resources from
an untrusted PR. `run.sh` is an opt-in launcher for a workspace containing the
reviewed task-contract resources it names; these resources are **not all
implemented here**.

The controller must provide an isolated writable `/workspace`, per-worker Pi
state, an authorized model configuration and separately supplied credentials.
The image does not provide a sandbox, an identity broker, or command-policy
enforcement. Apply pod RBAC, filesystem, capability and network restrictions
outside the image. Never mount a Docker socket or a human admin kubeconfig.

## SDK/controller status

`src/index.ts` and `src/controller.ts` are architectural scaffolding from
`docs/plans/headless-agent.md`, not a working controller. Imports such as
`gateway-model.js`, `restricted-tools.js`, `task-contract.js`, and
`run-observer.js` are absent. The old `bun run index.ts` instruction was both
mislocated and not executable; do not use it as a readiness check.

`package.json`/`bun.lock` describe the earlier SDK experiment, not the image's
runtime dependencies. Its old Pi dependency has not been promoted into the
image. Implement and verify the missing controller modules before choosing
its own Node/Bun build pipeline; do not mistake a successful RPC image build
for a verified issue-to-PR automation service.
