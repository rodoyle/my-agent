# Agent image automation verification — 2026-11-11

## Observed release

[GitHub Actions run 42960704684](https://github.com/rodoyle/my-agent/actions/runs/42960704684)
executed source revision `6971a5ae1a36cc4f93fa6ec5395ac10d1f964a66`
on native Linux amd64 GitHub-hosted runners.

- Attempt 1: prepare, build and publish all **success**.
- The prepare job refreshed public npm inputs and passed engine-strict locked
  installation plus source regression gates.
- Four real Kaniko builds, exact-base chaining and all four runtime smoke gates
  passed against the credential-free loopback registry. Headless also passed
  its default-command closed-stdin gate.
- The separate authenticated job loaded the checksum-verified archive and
  successfully pushed all four unique tags and all four `latest` aliases.
- Attempt 2 explicitly reran **only publish** (original job `130328617704`). It
  succeeded using the successful build's original artifact and
  `run-42960704684-1` tag, not a nonexistent attempt-2 build artifact. Its
  downloaded publication receipt is identical to attempt 1's four digest results.

| GHCR image | Published digest |
| --- | --- |
| `ghcr.io/rodoyle/agents-base` | `sha256:7320023cf316fb78a148ad0fcf9eaaa264b12fb7258454c70173d0d74fc209fc` |
| `ghcr.io/rodoyle/agents-devpod` | `sha256:0fafca233d7c9c147f626b825e6fd545070dfe43a32055bc5aeff946ba4404f1` |
| `ghcr.io/rodoyle/agents-headless` | `sha256:0d1f7fb847c4881be382ccf8269b79e51c23cd206154e01823db1fab075c41e7` |
| `ghcr.io/rodoyle/agents-template` | `sha256:e85a7d70d2e70b4a3a6fda1f0df40eb978466f2ca2bf07d91386447fd180c038` |

Non-secret downloaded receipts are preserved in
`evidence/agent-images-ci-2026-11-11-build.json` and
`evidence/agent-images-ci-2026-11-11-publication.json`.
The local-registry build digests differ from GHCR digests after Docker archive
load/push manifest conversion; deployment references are the GHCR receipts above.

Resolved inputs selected Pi **1.5.2**, GLLA **0.39.69**, intercom **0.18.1**,
pi-lens **4.4.12**, pi-subagents **0.88.0**, and Kubernetes client **2.0.2**.
The receipt records SHA-256 of both runtime input files and the tested archive.
Full input pairs remain in current-run artifacts and the published images.

## Source and failure gates

From the agents checkout:

- `timeout 120 python3 -m unittest discover -s tests -v`: **22 passed**.
- `timeout 60 node --test tests/profile-config.test.mjs`: **4 passed**.
- `timeout 120 pre-commit run --config ../.pre-commit-config.yaml --all-files`:
  hardcoded-secret scan passed.
- Final active LSP probes of the builder, updater, publisher, policy, release
  tests, workflow, automation documents, README and environment pin: ten files
  checked, zero error diagnostics.
- `git diff --check`: passed.

Adapter tests deliberately fail smoke execution, malformed digests, resolver
queries/locking, interrupted snapshot publication, archive verification and
unique-tag pushes. The stale-source test permits unique-tag publication but
rejects every `latest` change after main advances. The schedule-then-push policy
requires refresh for both automatic events. These are bounded source tests, not
claims that live CI failure modes were deliberately induced.

## Review decisions and boundaries

The fresh read-only review initially blocked the read-only `/workspace` context
collision and identified credential exposure during dependency builds. Both were
corrected: `/context` is independent of image workdirs, and image execution is
completed on a different runner before GHCR authority is introduced.

Further accepted corrections were atomic new-directory snapshots, always-run
labelled-container cleanup, current-main checks before each alias push, and
producer-owned artifact/tag outputs for partial reruns. The reviewer had no
execution tool; the parent executed source checks and observed the real CI runs.
The superseded initial workflow run `42960299941` was intentionally cancelled
before publication after the follow-up fixes were prepared; it is not release
success evidence.

- The downgrade guard compares npm candidates with committed input pins, not
  the previous GHCR publication. Npm retags above that baseline can still lower
  a published version; this limitation is explicit in the automation guide.
- Main-head checks and registry alias changes are not one atomic transaction.
  A remote change/network failure can still leave partially advanced aliases;
  deploy exact GHCR digests for coordinated multi-image releases.
- Weekly cron registration and manual dispatch are configured; the observed
  initial full run was a main push, followed by a publish-only rerun. No weekly
  scheduler delivery is fabricated.
- No cluster access, operator grant, credentials created by the agent, provider
  inference, browser pairing, arm64 build or production deployment was needed.
  Package visibility/pull authorization remains owner-controlled; GHCR accepted
  this repository's short-lived publication token without additional setup.

See `agent-image-automation.md` for invocation, recovery, permissions and
artifact-retention policy. Subsequent documentation-only commits do not change
the executable source tested at the revision above.
