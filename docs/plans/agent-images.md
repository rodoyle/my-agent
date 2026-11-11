# Agent images: runtime decision, implementation and build procedure

## Scope

Turn the comment-only `base/Dockerfile` and `devpod/Dockerfile` into usable,
consistent images. Provide inherited headless/template Dockerfiles, not a new
issue controller or model gateway. The existing headless SDK sources reference
missing modules and remain explicitly experimental. The macOS/MLX Python
`local-agent/` is a separate host application, not a Linux image dependency.

All Dockerfiles use **the agents repository root as build context**. Use Kaniko
in the k3s **`build` namespace** for manual cluster builds, or the isolated
GitHub-hosted CI path in [image automation](agent-image-automation.md). Neither
path uses local Docker/Podman builds. The parent infra repository tracks this
repository as a submodule; commit inside `agents/` before updating its gitlink.

## Node/npm versus Bun

Use **Node 22.23.4 + its npm** for the Pi CLI, SDK dependencies selected for
these images, extensions and subagent processes. Upstream Pi 1.5.0 declares
`node >=22.19.0`, and its README documents npm installation. This is a supported
baseline, not a claim that Bun can never host Pi: upstream RPC documentation
explicitly mentions SDK integrations hosted by either Node or Bun.

Use **Bun 1.4.4** for Ovis and project tooling. Ovis requires Bun >=1.4; Bun is
therefore a real dependency, not an alternative spelling of `node` or `npm`.
Never symlink `node` to Bun, invoke Pi via `bun --bun`, or maintain an independent
Bun-installed Pi runtime in derived images. Existing project-specific Bun
lockfiles do not determine the base image's Pi version.

### Pins and sources

| Component | Selected version/source |
| --- | --- |
| Distribution/Node | `node:22.23.4-bookworm-slim` (glibc) |
| Bun | `oven/bun:1.4.4`, binary copied from its native image |
| Pi CLI | `@earendil-works/pi-coding-agent@1.5.0` |
| Kubernetes JS client | `@kubernetes/client-node@2.0.2` |
| Extensions | `pi-subagents@0.87.0`, `pi-lens@4.4.10`, `pi-goal-list-loop-audit@0.39.65`, `pi-intercom@0.18.1` |
| Herdr | `0.9.5`, architecture-specific release binary + committed SHA-256 |
| Web UI | `devswha/ovis` (formerly `devswha/herdr-web-ui`), release `0.5.1`, commit `c99017754cb330143589afb2f74473828b86615e` |
| kubectl | `v1.36.6`, release checksum verified; matches the 1.36 cluster API |
| Kaniko | `gcr.io/kaniko-project/executor:v1.23.2` |

`base/runtime/package-lock.json` locks the npm transitive dependency graph.
Install with `npm ci --ignore-scripts`; explicitly run only ast-grep's binary
linking postinstall, since pi-lens needs its native CLI. The `piImage.extensions`
list in `base/runtime/package.json` is the shared extension catalog; versions
remain in `dependencies` and the lockfile, not in Dockerfile install loops.
`base/profile-config.mjs` compiles the profiles into Pi's documented **local
package** settings with absolute sources under `/opt/pi-runtime/node_modules`.
A mounted HOME therefore does not need to download/reinstall packages.

Ovis gets its own upstream frozen Bun lockfile. Its release PTY host installer
checks that the binary matches the checked-out Rust source tree and release
checksum. Build its frontend once, then copy the prepared tree into the final
image. Runtime invokes `server/index.ts`, not `bun run start` (which rebuilds)
or a self-updating managed launcher. No third-party curl-to-shell installers.

Image tags and Debian package indexes can still change; these are version pins,
not a claim of bit-for-bit reproducibility. Record the built image **digest**
and pass that exact reference to derived builds. Both amd64 and arm64 upstream
artifacts exist, but each platform needs its own native Kaniko build/smoke run;
artifact availability alone is not a verified multi-architecture release.

Primary sources consulted:

- [Pi README and Node requirement](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md)
- [Pi package/local-source installation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)
- [Pi RPC and SDK runtime distinction](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md)
- [Pi environment controls](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/environment-variables.md)
- [Herdr release manifest](https://herdr.dev/latest.json)
- [Ovis installation/runtime requirements](https://github.com/devswha/ovis/blob/v0.5.1/INSTALL.md)
- [Ovis pinned manifest](https://github.com/devswha/ovis/blob/c99017754cb330143589afb2f74473828b86615e/package.json)

## Image responsibilities and startup

- **Base:** Node/npm, Bun, Pi and four registered packages, Kubernetes JS
  library, Herdr, compiled Ovis and checked native PTY host, git, gh, jq,
  curl and tini. Default command `pi`.
- **Devpod:** inherits the base; adds kubectl, tmux, SSH client, ripgrep,
  fd, terminal/editor tools and Bash completion. Default command `bash`.
- **Headless:** inherits base; default Pi RPC command has no sessions,
  no project approval, and no extension/skill/prompt/context discovery.
  An external controller must explicitly select reviewed executable resources.
- **Template:** inherits base and retains `pi`; add only specialist tools.

UID/GID **1000:1000**, user `agent`, HOME `/home/agent`, workdir `/workspace`.
The Node image's existing uid-1000 user is renamed, not duplicated. No sudo,
credentials, kubeconfig, API keys, git identity or cluster grant is baked in.
Tini remains the entrypoint for signal forwarding and child reaping; overriding
`command` in Kubernetes bypasses it, so override `args` when possible.

### Declarative agent profiles

`base/profiles/*.json` defines the intentional configuration differences:

| Profile / image | Packages and settings |
| --- | --- |
| `base` | Entire installed extension catalog; project trust asks first |
| `devpod` | Inherits base; explicitly selects interactive built-in tools |
| `headless` | No catalog packages; project trust never; default CMD also disables executable-resource discovery |
| `template` | Inherits base; starting point for specialist selection |

A profile may `extends` one other profile. Settings shallowly override inherited
settings. Omitted `packages` inherits the selection; `"all"` selects the catalog,
`[]` selects none, and an array replaces the inherited selection. Package entries
are names or objects such as `{"name":"pi-lens","extensions":[],"skills":[]}`.
Resource filters use Pi's normal extensions/skills/prompts/themes semantics;
empty arrays disable that resource type. `settings.defaultTools` selects tools,
including Pi's `+name`/`-name` syntax. Profiles cannot select uninstalled packages
or remote sources. Cycles, unknown fields/packages and invalid selections fail
the build rather than silently dropping configuration.

Each image sets `AGENT_PROFILE`; the build compiles defaults under
`/opt/pi-defaults/<profile>/settings.json`. Mount writable per-worker `/workspace`
and `/home/agent` (or the configured Pi/session/state paths). On startup,
`agent-entrypoint` initializes the selected profile in `PI_CODING_AGENT_DIR`.
A `.image-profile.json` hash marker permits refreshing unchanged image-managed
settings when the image or profile changes. Operator-edited settings and legacy
unmarked settings are preserved, including intentional package filters. To adopt
new defaults deliberately, back up and remove `settings.json` before restarting.
Never share one writable agent directory between running workers. Immutable code
remains under `/opt/pi-runtime` and `/opt/ovis`; do not mount over it.

`PI_OFFLINE=1`, `PI_TELEMETRY=0` and `PI_SKIP_VERSION_CHECK=1` avoid automatic Pi
network refreshes, **not provider requests or arbitrary extension traffic**.
pi-lens can download optional language/security tools when needed; provide a
writable cache and authorized egress or pre-provision those tools in a
specialist image. No default security analyzers are disabled just to pass
image checks. A Kubernetes library is available within `/opt/pi-runtime`;
workspace applications must still declare their own dependencies for module
resolution. Global install paths are not implicit ESM import paths.

### Herdr/Ovis (opt-in services)

The default image does not start services, open public ports, or generate
access credentials. As the same user, start `herdr server` separately, then
run `ovis` in the foreground. The wrapper uses the baked assets and defaults
to `HOST=127.0.0.1`, `PORT=7317`; it rejects every non-loopback binding unless
a user-supplied `OVIS_TOKEN` is present. Never print that value. Route any
remote access through authorized TLS/authenticated ingress and network policy;
a token is not a replacement for TLS. Persist Ovis state deliberately: its
upstream server may create pairing/push identity material on first use, so
credential provisioning/startup belongs to the user or trusted deployment,
not an autonomous image-verification step. Browser/session functionality is
not claimed solely because the frontend builds.

## Least-privilege Kaniko builds

The parent `environment.yaml` currently pins base identity only. A manual
cluster build requires explicitly pinning and obtaining the temporary
`build/pi-agent-image-build-task` Role. The user mints
`~/.kube/agent.kubeconfig` and applies
`../manifests/build/agent-image-task-access.yaml` from the infra root. It permits
Jobs, context ConfigMaps and smoke Pods only in `build`, plus logs/events.
No operator grant, exec/attach/cp, host mounts or direct secret operations.

`scripts/kaniko-build.py` renders JSON (valid Kubernetes YAML) and makes no
cluster calls. It packages an explicit source allowlist, not the whole repo or
HOME. ConfigMap projections contain symlinks; an init container copies them
with `cp -LR` into an emptyDir before Kaniko COPY reads them. This avoids the
known empty/symlinked build-context failure without embedding a huge source
payload in a Dockerfile. Job names are source-derived, retries are bounded,
service-account tokens are unmounted and resource/deadline limits are explicit.

From the **agents/** directory, using the shim-first PATH and agent identity:

```sh
export PATH="$HOME/bin:$PATH"
# On this macOS host, configure the shim's backend if autodiscovery needs it:
export KUBECTL_REAL=/opt/homebrew/bin/kubectl
KUBECONFIG="$HOME/.kube/agent.kubeconfig"
export KUBECONFIG

python3 scripts/kaniko-build.py base \
  --destination 192.168.0.48:30500/agents-base:<unique-tag> \
  --insecure-registry 192.168.0.48:30500 > /tmp/agents-base-build.json
kubectl create --dry-run=server -f /tmp/agents-base-build.json
kubectl create -f /tmp/agents-base-build.json
# Read the generated Job name, then use a bounded wait and inspect logs.
timeout 1200 kubectl wait -n build --for=condition=complete \
  job/<generated-name> --timeout=1150s
kubectl logs -n build job/<generated-name> -c kaniko
# Successful Kaniko termination message contains the pushed sha256 digest.
kubectl get pods -n build -l app.kubernetes.io/instance=<generated-name> \
  -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}'
```

The internal registry NodePort was observed at `192.168.0.48:30500`; recheck
`build/registry` and node addresses before reusing it elsewhere. HTTP is an
explicit exception for that internal registry only. No registry credential is
read, mounted or inferred. For an authenticated registry, the user/trusted
builder must provision and authorize registry access separately.

Then render `devpod`, `headless` and optionally `template` with their own unique
`--destination` and `--base-image <registry>/agents-base@sha256:<built-digest>`.
Use the same explicit `--insecure-registry` only for the internal registry.
Repeat server dry-run/create/wait/log inspection for each. Do not use the
fallback `:latest` in a release. Revoke the temporary RoleBinding after all
build/smoke work and restore the task permission pin to base identity.

## Verification gates

Local regression checks (no provider/cluster credentials needed):

```sh
timeout 60 python3 -m unittest discover -s tests -v
node --test tests/profile-config.test.mjs
node --check base/profile-config.mjs
node --check tests/image-smoke.mjs
sh -n base/agent-entrypoint.sh base/ovis.sh
```

The behavioral fixtures protect source allowlisting, real-file staging,
source-derived build identity, required explicit base references, empty HOME
initialization, preservation of operator settings, exit-code propagation and
rejection of unauthenticated remote Ovis binding. A harmless README change
must not invalidate a build; an actual runtime source change must.

All four Dockerfile RUN gates execute as UID 1000. They query
Node/npm/Bun/Pi/Herdr/git/gh/ast-grep versions, import the Kubernetes client,
parse JavaScript with native ast-grep, and start real Pi RPC. `get_state` and
`get_commands` must succeed, with extension commands matching the selected
profile's package paths (including none for headless). No LLM prompt, token, external provider, or user
credential is needed. Devpod also runs `kubectl version --client`.

Build logs and image digests are recorded separately after actual cluster
verification. A failed build is not a delivered image; diagnose its signature,
change one relevant cause, and rerun the failed check plus regression checks.
Do not rerun unchanged failures or suppress extension/native checks.
