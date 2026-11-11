# Automated Pi updates and GHCR images

## Entry points

`.github/workflows/agent-images.yml` in `rodoyle/my-agent` supports:

- Mondays at **04:23 UTC**: refresh Pi/catalog extensions, rebuild and publish.
- Relevant pushes to `main`: refresh before rebuilding and publishing, so an
  old committed baseline cannot automatically undo a scheduled refresh.
- Manual dispatch: explicitly choose refresh and `latest` promotion.

```sh
gh workflow run agent-images.yml -R rodoyle/my-agent \
  -f refresh_runtime=true -f promote_latest=true
```

`refresh_runtime=false` uses committed pins. Combine it with
`promote_latest=false` to check that baseline without changing release aliases.
Manually promoting unrefreshed baseline pins is an intentional rollback option,
not an automatic push policy. `scripts/ci-policy.py` owns this tested decision.

Schedules are best-effort. GitHub may pause schedules in inactive public
repositories; re-enable the workflow in the Actions UI when needed. Forks and
non-main dispatches cannot publish. There is no credential-bearing PR build.

This is the CI option, not a cluster CronJob. Kaniko builds on native Linux
amd64 GitHub-hosted runners. Docker only launches Kaniko, operates an ephemeral
loopback registry, executes smoke containers and transfers tested images. No
Docker build, local Mac image build, kubeconfig or cluster grant is needed.

## Exact dependency snapshots

`scripts/refresh-runtime.py` queries public npm for Pi and the
`piImage.extensions` catalog in `base/runtime/package.json`. It refuses
prereleases, non-exact pins and downgrades. Unlisted dependencies remain pinned;
Node, Bun, Herdr, Ovis and kubectl are not silently upgraded.

Resolution uses a temporary directory, disabled npm lifecycle scripts and no
personal npm configuration. The tool **never edits source inputs**. It publishes
both validated files together by renaming a new snapshot directory atomically.
Interrupted resolution/output cannot select a partial input pair. The output
path must not exist; interrupted staging directories may be removed afterward.

```sh
timeout 600 python3 scripts/refresh-runtime.py \
  --output-directory /tmp/new-agent-runtime
```

To adopt those source pins deliberately, compare the generated pair with
`base/runtime/` and copy both into a clean, git-checkpointed checkout for review.
CI copies a complete snapshot into a disposable checkout, then engine-strict
`npm ci` and runtime gates reject incompatible releases. The CI copy is not an
in-place source update service and never commits or opens a bot PR.

Scheduled publications therefore use resolved inputs different from committed
baseline pins. Actual manifests/lockfiles are baked into `/opt/pi-runtime` and
preserved with release receipts. An image's git revision label alone does not
describe its dependency graph. Refresh-enabled reruns resolve npm again and need
not reproduce an earlier attempt; use saved input pairs for reproduction.

## Credential-free build and execution

The prepare and build jobs have only `contents: read`. Checkout credential
persistence is disabled. No publication token or auth directory is passed into
Kaniko, Dockerfile commands, dependency installers or runtime smoke containers.

`scripts/ci-release.py` stages only the existing source allowlist at `/context`,
not `/workspace` (which is a writable image workdir). It rejects symlink escapes.
Git metadata, npm config, HOME, sessions and registry auth are not context inputs.
The builder pushes only to a job-local **unauthenticated** `localhost:5000`
registry, bound to runner loopback. Kaniko uses host networking to reach it; this
is an explicit HTTP exception for the disposable local registry, not GHCR.

Base is built and tested first. Devpod, headless and template consume its exact
executor-produced digest. Every Dockerfile has a non-root native/Pi gate. Each
pushed local digest is then pulled and run with empty HOME/workspace, no runtime
network, read-only root, dropped capabilities and no credentials. Real Pi RPC
checks profile package commands; headless also runs its default CMD with closed
stdin. No provider inference or authenticated service is exercised.

Only after every image passes does the builder export one Docker archive
(sharing common layers) plus a SHA-256 build receipt. Per-command timeouts remove
owned containers; an always-run workflow cleanup also removes labelled builder,
smoke and registry containers after an outer process timeout. Runner disposal is
the final boundary if cleanup itself cannot run.

## Separate authenticated publication

A **different runner/job** receives the tested archive through a current-run
artifact. Only this job receives GitHub's short-lived `GITHUB_TOKEN` with
`packages: write` and `contents: read`. It does not run Dockerfile commands or
execute any image code. `scripts/publish-images.py` verifies the expected source
revision/run, all smoke receipts and the archive hash, then loads, tags and
pushes already-tested bytes. It never builds or runs containers.

Destinations are `ghcr.io/rodoyle/agents-{base,devpod,headless,template}`. Each
gets `run-<GitHub run id>-<attempt>`. Successful GHCR push digest receipts—not
local build digests or mere source metadata—form `publication.json`. Registry
manifest representations may change during archive load/push, so use those
final GHCR digests for deployment.

Only after all four unique-tag pushes succeed can `latest` be promoted.
`promote_latest=false` still publishes and verifies unique tags. A build, smoke
or unique-tag push failure never reaches alias promotion. Four registry aliases
cannot be updated atomically: a network error during promotion can advance only
some aliases. All images were already tested, but use report digests rather than
assuming a multi-image `latest` transaction.

GitHub mints the token; no PAT, SSH key, provider token or Kubernetes credential
is required. Login uses stdin. Auth is outside source/artifact paths and removed
by always-run cleanup. Build dependencies never receive registry write authority.
Actions/GHCR policy must permit repository-token publication. Existing packages
without repository linkage may need their owner to grant Actions access in
package settings. The user controls visibility (new packages may be private)
and deployment pull authorization; do not bypass policy with a personal token.

## Evidence and recovery

Runtime-input and build/publication JSON artifacts are retained **90 days**.
The large tested-image archive is a one-day handoff artifact. Runtime manifests
also remain in published images. No automated image/tag deletion is performed.
Failed attempts preserve partial JSON reports when available; a failed build or
publication is not a successful release.

For reproduction, check out the receipt's revision, restore its runtime input
pair from artifacts or an image, and run the credential-free builder on native
Linux amd64 with a loopback registry. Feed the tested archive to the publisher
with a new unique run tag on a separate authorized runner. CLI `--help` lists
all arguments. Never add publication credentials to the builder for convenience.

Local source checks need no Docker or credentials:

```sh
timeout 120 python3 -m unittest discover -s tests -v
timeout 60 node --test tests/profile-config.test.mjs
```

Tests protect update boundaries and atomic snapshot selection, no-op byte
preservation, rollback/downgrade rejection, source isolation, exact-base chaining,
smoke failures, archive integrity, authenticated non-execution, publication
failures and schedule-then-push policy. Inert adapters do not replace the real
CI Kaniko/build/smoke/GHCR push evidence.
